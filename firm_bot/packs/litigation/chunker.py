"""Litigation-pack chunker overlays.

Litigation documents have a different structure than contracts:

* **Depositions and hearing transcripts** are formatted as alternating
  ``Q. …`` / ``A. …`` lines, often with leading page:line markers like
  ``[42:15]``. The base markdown chunker (which recognises
  ``Article/Section/Exhibit`` patterns) does not understand Q/A pairs or
  line numbers.

* **Pleadings (complaints, motions, briefs)** organise argument as
  *numbered paragraphs* (``14. Plaintiff pleads…``). The pleading
  paragraph number is the primary citation handle; a chunk that splits
  ``14.`` from ``15.`` destroys the citation's meaning.

This module provides two chunker functions the pack registers when
``register()`` is called. They are deliberately **not** automatic: a
firm that does not load the litigation pack continues to use the base
``firm_bot.chunk.chunk_documents`` chunker.

The functions return plain ``list[str]`` (chunk texts) so they compose
naturally with the base chunker's ``Chunk`` dataclass — callers convert
the strings into ``Chunk`` objects with their own metadata.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Matches a transcript page:line marker such as ``[42:15]`` or
# ``[42:15-43:2]`` (a single citation often spans a contiguous range).
# Used to detect the start of a new page in a transcript dump.
RE_PAGE_LINE = re.compile(r"^\s*\[(\d+):(\d+)(?:\s*-\s*(\d+):(\d+))?\]")

# Matches a Q. line in a transcript (NOT an A. line). The chunker
# treats Q. as a section start so a chunk opens on a question; A.
# lines are continuation of the same Q. pair and never start a new
# chunk (otherwise every Q/A pair would split into two chunks, which
# destroys the natural read order and dilutes embeddings).
RE_QA = re.compile(r"^\s*Q\.\s+", re.IGNORECASE)

# Matches a numbered paragraph opener in a pleading. Common forms:
#   14.  Plaintiff pleads…
#   14.  Plaintiff incorporates by reference…
#   ¶ 14. Plaintiff pleads…   (rare in our corpus but legal docs vary)
#   14 .  Plaintiff pleads…   (extra space tolerated)
RE_PLEADING_PARA = re.compile(r"^\s*(?:¶\s*)?(\d+)\s*\.\s+\S")


def chunk_transcript(
    text: str,
    lines_per_chunk: int = 50,
) -> list[str]:
    """Split a transcript dump into Q/A-aware chunks.

    Strategy:

    1. Walk the input one line at a time. Two kinds of boundary are
       detected:
       * ``[page:line]`` marker — HARD boundary, always flushes.
         Witnesses often change topic between pages.
       * ``Q.`` line — SOFT boundary. The chunker continues to
         accumulate until either the soft cap (``lines_per_chunk``)
         is reached OR another hard boundary fires. This keeps
         consecutive Q/A pairs in the same chunk so the embedding
         captures the conversational thread instead of fragmenting
         every question+answer into a 2-line chunk.
       * ``A.`` lines are never boundaries — they always continue the
         current Q. pair (otherwise every Q/A pair would split).
       * A hard cap at ``lines_per_chunk`` (the chunker never lets a
         single chunk run past this many lines even if no boundary
         was found — protects against very long witness answers).

    2. Each chunk is the concatenation of lines from one flush to the
       next. The first line of every chunk is either a page:line
       marker or a Q. line — never an answer fragment.

    3. Whitespace is normalised (single newline preserved; trailing
       whitespace stripped).

    Returns a list of non-empty chunk strings. Empty input returns
    ``[]``.
    """
    if not text or not text.strip():
        return []
    lines = text.splitlines()
    chunks: list[str] = []
    buf: list[str] = []
    line_count = 0

    def flush() -> None:
        nonlocal buf, line_count
        if buf:
            joined = "\n".join(buf).strip()
            if joined:
                chunks.append(joined)
        buf = []
        line_count = 0

    for line in lines:
        is_hard_boundary = bool(RE_PAGE_LINE.match(line))
        is_q_line = bool(RE_QA.match(line))
        # hard boundary flushes regardless; soft (Q.) only flushes if
        # we've already crossed the soft cap (lets us chunk multiple
        # Q/A pairs together up to lines_per_chunk).
        if (is_hard_boundary and buf) or (is_q_line and line_count >= lines_per_chunk and buf):
            flush()
        elif not is_q_line and not is_hard_boundary and line_count >= lines_per_chunk and buf:
            # also flush at the soft cap on continuation lines
            flush()
        buf.append(line)
        line_count += 1
    flush()
    return chunks


def chunk_pleading(  # noqa: PLR0912  (state machine — flattening hurts readability)
    text: str,
    paragraphs_per_chunk: int = 10,
) -> list[str]:
    """Split a pleading into numbered-paragraph-aware chunks.

    Strategy:

    1. Detect paragraph boundaries by leading ``N.`` tokens at line
       start. These are the standard pleading-paragraph citation
       handles; chunks must not split between them.
    2. Group paragraphs into chunks of up to ``paragraphs_per_chunk``
       consecutive paragraphs. A short pleading (fewer paragraphs than
       the cap) becomes a single chunk.
    3. Pre-paragraph content (caption block, signature line) becomes
       its own "preface" chunk so it stays searchable on its own
       rather than merging with paragraph 1.

    Returns a list of non-empty chunk strings. Empty input returns
    ``[]``.
    """
    if not text or not text.strip():
        return []
    lines = text.splitlines()

    # Bucket lines: either "preface" (before first numbered para) or a
    # numbered paragraph group.
    groups: list[list[str]] = []
    preface: list[str] = []
    in_paragraph = False
    current: list[str] = []

    def close_para() -> None:
        nonlocal current, in_paragraph
        if current:
            groups.append(current)
        current = []
        in_paragraph = False

    for line in lines:
        m = RE_PLEADING_PARA.match(line)
        if m:
            # start of a new numbered paragraph
            if not in_paragraph:
                # first para — anything we accumulated so far is preface
                if preface:
                    groups.append(preface)
                    preface = []
            else:
                # closing the previous para
                close_para()
            in_paragraph = True
            current = [line]
        elif in_paragraph:
            current.append(line)
        else:
            preface.append(line)
    # tail
    if current:
        close_para()
    elif preface:
        # only preface, no numbered paras at all
        groups.append(preface)

    # Now slice body groups into chunks of paragraphs_per_chunk
    # consecutive groups each. The preface (if any) is always emitted
    # as its own chunk — never merged with body paragraphs — so the
    # answer layer can render the caption block separately from the
    # numbered argument.
    out: list[str] = []
    preface_block: list[str] | None = None
    body_groups: list[list[str]] = []
    for g in groups:
        # The preface is the only group whose first line does not start
        # with a numbered paragraph.
        if not g or not RE_PLEADING_PARA.match(g[0]):
            if preface_block is None:
                preface_block = g
            else:
                body_groups.append(g)
        else:
            body_groups.append(g)
    if preface_block is not None:
        joined = "\n".join(preface_block).strip()
        if joined:
            out.append(joined)
    for i in range(0, len(body_groups), paragraphs_per_chunk):
        block = body_groups[i : i + paragraphs_per_chunk]
        joined = "\n".join("\n".join(g) for g in block).strip()
        if joined:
            out.append(joined)
    return out


def chunk_iter(text: str, boundaries: Iterable[int]) -> list[str]:
    """Generic helper: split ``text`` at the given character offsets.

    Used by tests and by callers that want to apply their own
    boundary-detection logic on top of the litigation pack's
    primitives. Offsets must be sorted ascending and lie within
    ``len(text)``.
    """
    if not text:
        return []
    offsets = sorted(set(boundaries))
    if not offsets or offsets[0] != 0:
        offsets = [0, *offsets]
    if offsets[-1] != len(text):
        offsets.append(len(text))
    parts: list[str] = []
    for i, start in enumerate(offsets[:-1]):
        end = offsets[i + 1]
        piece = text[start:end].strip()
        if piece:
            parts.append(piece)
    return parts
