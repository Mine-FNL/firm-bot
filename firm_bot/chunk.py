"""Smart chunker for firm-bot.

Why a custom chunker instead of a generic sliding-window splitter:

Legal documents and contracts have clause boundaries. Splitting a 30-page
MSA in half by character count produces chunks that contain half a
limitation-of-liability clause — a chunk the operator cannot cite
because it doesn't make sense in isolation. The retriever then returns
nonsense when the user asks "what's the cap on our indemnity?"

This chunker:
1. Pre-splits the text into "sections" using structural cues (numbering,
   all-caps headings, MD/Word headings already present in metadata).
2. Splits over-long sections at sentence boundaries (preserves a small
   overlap for context).
3. Merges tiny adjacent chunks so the retriever doesn't fragment
   trivial passages into 50-character slivers.

Metadata flows from the parent ``Document`` into every chunk, augmented
with ``chunk_index`` and an estimated ``char_offset`` for debugging.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from .ingest.common import Document

log = logging.getLogger("firm_bot.chunk")

# --- structural patterns --------------------------------------------------

# Match headings at line start:
#   "Article I", "Article 1.", "ARTICLE I", "Section 4.2"
#   "1. Introduction", "1.2 Background", "12.3.4 Sub-clause"
#   "EXHIBIT A", "SCHEDULE 1"
#   "Term", "Governing Law", "Permitted Disclosures"  (Title Case short line)
#   "RECITALS", "WHEREAS", "NOW THEREFORE"            (legal preamble)
#
# The Article/Section/etc. branches are case-insensitive (case flags
# "Article", "SECTION", "ARTICLE" all show up in the wild). The
# numbered ("1.2 Foo"), ALL-CAPS, and Title-Case branches stay
# case-sensitive to avoid catching arbitrary lines.
#
# The Title-Case branch matches a single line that:
#   - starts at line beginning
#   - is 2-6 words, each Title-Case (or 1 word of >=5 chars)
#   - has no terminal punctuation other than possibly "." at end
#   - is ≤ 60 chars total
# This catches common contract section titles ("Term", "Governing Law",
# "Permitted Disclosures") that aren't prefixed with Article/Section.
# The 5-char min prevents one-word proper nouns ("Bob", "Alice") from
# being treated as section headings.
RE_SECTION = re.compile(
    r"^(?:"                                                              # group
    r"(?i:article|section|chapter|schedule|exhibit|annex|appendix)\s+"   # word (CI)
    r"(?:[A-Z0-9]+(?:\.[A-Z0-9]+)*\.?"                                   # numbering
    r"|[IVXLCDM]+\.?)"                                                    # roman
    r"|"
    r"\d+(?:\.\d+){0,4}\s+[A-Z][A-Za-z]"                                  # 1.2 Foo
    r"|"
    r"[A-Z][A-Z0-9 ]{4,}$"                                                # ALL CAPS line
    r"|"
    r"(?:"                                                                # Title Case short line
    r"(?:[A-Z][a-z]{3,}"                                                  # single Title word (>=4 chars)
    r"|[A-Z][a-z]+\s+(?:[A-Z][a-z]+\s+){0,4}[A-Z][a-z]+)"                 # 2-5 Title words
    r")\.?"
    r"$"
    r")",
    re.MULTILINE,
)

# Match legal preamble markers
RE_PREAMBLE = re.compile(
    r"^(?:WHEREAS|NOW,?\s*THEREFORE|RECITALS?|DEFINITIONS?)[:\s]",
    re.MULTILINE | re.IGNORECASE,
)

# Sentence boundary — keep simple; English business prose is our target.
RE_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {"chunk_id": self.chunk_id, "text": self.text, "metadata": self.metadata}


def _split_into_sections(text: str) -> list[str]:
    """Split a Document's text into structural sections.

    Returns a list of section strings (each starts with the section
    heading it was sliced on, so context is preserved). Sections that
    don't match any structural pattern fall through as a single "body"
    section.
    """
    if not text.strip():
        return []

    # Find all candidate boundary positions
    boundaries: list[int] = []
    for m in RE_SECTION.finditer(text):
        boundaries.append(m.start())
    for m in RE_PREAMBLE.finditer(text):
        boundaries.append(m.start())

    # Always include the document start
    if not boundaries or boundaries[0] != 0:
        boundaries.insert(0, 0)
    boundaries = sorted(set(boundaries))

    if len(boundaries) <= 1:
        return [text]

    sections: list[str] = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            sections.append(chunk)
    return sections


def _split_long_section(section: str, chunk_size: int, overlap: int) -> list[str]:
    """Split a section that exceeds chunk_size at sentence boundaries.

    The last ``overlap`` characters of each split leak into the next so
    the retriever doesn't lose context at the boundary. We bias the
    overlap to land on a sentence boundary when possible.
    """
    if len(section) <= chunk_size:
        return [section]

    parts: list[str] = []
    cursor = 0
    n = len(section)
    while cursor < n:
        target_end = min(cursor + chunk_size, n)
        if target_end < n:
            # back off to the last sentence boundary in the last 30% of
            # the window so we don't end mid-word.
            window_start = cursor + int(chunk_size * 0.7)
            tail = section[window_start:target_end]
            # find the rightmost sentence-end inside the tail
            matches = list(RE_SENT_END.finditer(tail))
            if matches:
                last = matches[-1]
                target_end = window_start + last.end()
            else:
                # last resort: split on the nearest space
                sp = section.rfind(" ", cursor, target_end)
                if sp > cursor + chunk_size // 2:
                    target_end = sp
        chunk = section[cursor:target_end].strip()
        if chunk:
            parts.append(chunk)
        if target_end >= n:
            break
        # advance with overlap
        cursor = max(target_end - overlap, cursor + 1)
    return parts


def _merge_tiny_in_section(chunks: list[str], min_size: int) -> list[str]:
    """Merge consecutive sub-min_size chunks WITHIN a single section.

    Sections are kept separate — Article II must NOT be merged into
    Article I just because both happen to be short. We are called once
    per section.
    """
    if not chunks:
        return chunks
    merged: list[str] = []
    buf = ""
    for c in chunks:
        if len(c) < min_size:
            buf = (buf + "\n\n" + c).strip() if buf else c
            continue
        if buf:
            merged.append((buf + "\n\n" + c).strip())
            buf = ""
        else:
            merged.append(c)
    if buf:
        if merged:
            merged[-1] = (merged[-1] + "\n\n" + buf).strip()
        else:
            merged.append(buf)
    return [c for c in merged if c.strip()]


def chunk_documents(
    documents: Iterable[Document],
    chunk_size: int = 1200,
    overlap: int = 200,
    min_size: int = 120,
) -> list[Chunk]:
    """Chunk a stream of Documents into retriever-friendly units.

    Each Document's metadata flows into every emitted chunk, augmented
    with ``chunk_index`` (0-based within the document) and the source
    heading (if any).

    Structure-aware:
    1. Pre-split the document into sections (Article, Section, etc.).
    2. Within each section, split over-long text at sentence boundaries.
    3. Within each section, merge sub-min_size fragments.

    Sections are kept distinct — two short articles do not collapse
    into one chunk just because they are both small.
    """
    out: list[Chunk] = []
    for doc in documents:
        sections = _split_into_sections(doc.text)
        sized: list[str] = []
        for sec in sections:
            # per-section: split long, merge tiny. Sections stay distinct.
            sized.extend(_merge_tiny_in_section(
                _split_long_section(sec, chunk_size, overlap),
                min_size,
            ))
        for i, text in enumerate(sized):
            cid = f"{doc.doc_id}:{i}"
            md = dict(doc.metadata)
            md["chunk_index"] = i
            md["parent_doc_id"] = doc.doc_id
            md["char_len"] = len(text)
            out.append(
                Chunk(
                    chunk_id=cid,
                    text=text,
                    metadata=md,
                )
            )
    log.debug("chunked %d inputs → %d chunks", len(documents) if isinstance(documents, list) else -1, len(out))
    return out
