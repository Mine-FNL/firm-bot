"""Litigation-pack extractors.

Adds two extractors that the base pipeline (``firm_bot.ingest.common``)
does not provide:

* :func:`extract_transcript` — handles deposition / hearing transcripts
  formatted as ``[page:line] Q. … / A. …`` lines. Each emitted ``Chunk``
  carries the page and line numbers as metadata so the answer LLM can
  cite ``[TX_foo.txt:p.42:L15]`` precisely.

* :func:`extract_pleading` — handles complaints, motions, answers, and
  briefs written as numbered paragraphs. Each emitted ``Chunk`` carries
  the starting and ending paragraph number as metadata so the answer
  LLM can cite ``[PL_complaint.txt:¶14-22]`` precisely.

Both extractors return ``list[Chunk]`` (per the v0.4 domain-pack spec).
The pack's :func:`firm_bot.packs.litigation.register` wraps them in a
``list[Document]`` adapter so they slot into the standard
``firm_bot.ingest.common.dispatch`` contract when the pack is loaded.

The pack is **opt-in**: until :func:`register` is called, the base
dispatch ignores ``.txt`` files and the litigation extractors are
inert. After :func:`unregister` (or process exit), the base dispatch is
fully restored.

Filename conventions used by the dispatch hook:

* ``TX_<witness>_<date>.txt`` → transcript extractor
* ``PL_<doc-kind>_<caption>.txt`` → pleading extractor
* ``EX_<id>_<short>.txt`` → pleading extractor (treats exhibits as
  pleadings for chunking purposes)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...chunk import Chunk
from ...ingest.common import Document, stable_doc_id
from .chunker import (
    RE_PAGE_LINE,
    RE_PLEADING_PARA,
    chunk_pleading,
    chunk_transcript,
)

# --- filename-prefix dispatch ---------------------------------------------

# Filename prefixes the dispatch hook recognises. Order is significant
# for tie-breaking; the first matching prefix wins.
TRANSCRIPT_PREFIX = "TX_"
PLEADING_PREFIXES = ("PL_", "EX_")


def classify(path: Path) -> str | None:
    """Return a class name for ``path`` or ``None`` if no pack rule applies.

    * ``"transcript"`` if the filename starts with :data:`TRANSCRIPT_PREFIX`
      AND the suffix is ``.txt``
    * ``"pleading"`` if the filename starts with any prefix in
      :data:`PLEADING_PREFIXES` AND the suffix is ``.txt``
    * ``None`` otherwise (caller falls back to the base pipeline).
      The suffix check stops the litigation prefix from misclassifying
      a PDF named e.g. ``PL_complaint.pdf`` — only ``.txt`` files
      are pack-handled.
    """
    if path.suffix.lower() != ".txt":
        return None
    name = path.name
    if name.startswith(TRANSCRIPT_PREFIX):
        return "transcript"
    for p in PLEADING_PREFIXES:
        if name.startswith(p):
            return "pleading"
    return None


# --- public extractors -----------------------------------------------------


def extract_transcript(path: Path) -> list[Chunk]:
    """Extract a transcript ``.txt`` file into page:line-aware chunks.

    Each ``Chunk``'s metadata carries:

    * ``extractor``: ``"litigation_transcript"`` — used by the answer
      layer to render the proper citation marker.
    * ``doc_class``: ``"transcript"`` — pack-level classification that
      the system-prompt suffix references.
    * ``source_path`` / ``source_name``: provenance.
    * ``page`` / ``line``: the page and line that open the chunk. If
      the chunk does not begin with a page:line marker (e.g. it opens
      on a Q. line in the middle of a page), ``line`` is the line
      number from the previous marker.
    * ``qa_start``: ``"Q"`` or ``"A"`` — whether the chunk opens on a
      question or an answer.

    The function never raises: a missing or unreadable file yields
    ``[]``. Empty files yield ``[]``. ``Page`` defaults to ``1`` when
    no page:line marker appears in the file.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text.strip():
        return []

    chunks = chunk_transcript(text)
    out: list[Chunk] = []
    page = 1
    line = 1
    for i, chunk_text in enumerate(chunks):
        first_line = chunk_text.splitlines()[0] if chunk_text else ""
        m = RE_PAGE_LINE.match(first_line)
        if m:
            page = int(m.group(1))
            line = int(m.group(2))
            qa = "?"
        else:
            # infer Q. or A. from the first non-empty token of first line
            stripped = first_line.lstrip().upper()
            qa = "Q" if stripped.startswith("Q.") else "A" if stripped.startswith("A.") else "?"
        out.append(
            Chunk(
                chunk_id=f"{stable_doc_id(str(path), f'tx-{i}')}:{i}",
                text=chunk_text,
                metadata={
                    "extractor": "litigation_transcript",
                    "doc_class": "transcript",
                    "source_path": str(path),
                    "source_name": path.name,
                    "page": page,
                    "line": line,
                    "qa_start": qa,
                    "chunk_index": i,
                },
            )
        )
    return out


def extract_pleading(path: Path) -> list[Chunk]:
    """Extract a pleading ``.txt`` file into paragraph-aware chunks.

    Each ``Chunk``'s metadata carries:

    * ``extractor``: ``"litigation_pleading"`` — used by the answer
      layer.
    * ``doc_class``: ``"pleading"`` — pack-level classification.
    * ``source_path`` / ``source_name``: provenance.
    * ``para_start`` / ``para_end``: the inclusive paragraph-number
      range covered by this chunk. ``0`` for the preface chunk (caption
      block before the first numbered paragraph).
    * ``kind``: ``"preface"`` for the caption-block chunk, ``"body"``
      for numbered-paragraph chunks.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text.strip():
        return []

    raw_chunks = chunk_pleading(text)
    out: list[Chunk] = []
    for i, chunk_text in enumerate(raw_chunks):
        first_line = chunk_text.splitlines()[0] if chunk_text else ""
        last_line = chunk_text.rstrip().splitlines()[-1] if chunk_text else ""

        m_first = RE_PLEADING_PARA.match(first_line)
        if m_first:
            kind = "body"
            para_start = int(m_first.group(1))
        else:
            kind = "preface"
            para_start = 0

        m_last = RE_PLEADING_PARA.match(last_line)
        if m_last:
            para_end = int(m_last.group(1))
        elif kind == "body":
            para_end = para_start
        else:
            para_end = 0

        out.append(
            Chunk(
                chunk_id=f"{stable_doc_id(str(path), f'pl-{i}')}:{i}",
                text=chunk_text,
                metadata={
                    "extractor": "litigation_pleading",
                    "doc_class": "pleading",
                    "source_path": str(path),
                    "source_name": path.name,
                    "para_start": para_start,
                    "para_end": para_end,
                    "kind": kind,
                    "chunk_index": i,
                },
            )
        )
    return out


# --- dispatch integration --------------------------------------------------


def _chunks_to_documents(
    chunks: list[Chunk], fallback_doc_id_seed: str
) -> list[Document]:
    """Convert pack-extractor ``Chunk`` output to ``Document`` for the
    standard ``firm_bot.ingest.common.dispatch`` contract.

    The base pipeline expects ``list[Document]``. Each Document becomes
    a single chunk downstream (the base ``chunk_documents`` is a no-op
    on tiny Documents). We carry the pack's metadata over verbatim
    so the answer layer sees ``extractor``/``doc_class``/``page``/etc.
    """
    out: list[Document] = []
    for c in chunks:
        out.append(
            Document(
                doc_id=c.chunk_id,
                text=c.text,
                metadata=dict(c.metadata),
            )
        )
    if not out and fallback_doc_id_seed:  # pragma: no cover - defensive
        # keep signature intent for callers that want to log a sentinel
        _ = fallback_doc_id_seed
    return out


# Original-dispatch slot for unregister. Stored in a single-element
# list so the registration helpers don't need a ``global`` statement
# (the list is mutated in place). Empty list = not registered.
_original_dispatch: list[Callable[[Path], list[Document]]] = []


def _pack_dispatch(path: Path) -> list[Document]:
    """Replacement for ``firm_bot.ingest.common.dispatch``.

    Behaviour:

    1. Defer to the original dispatch for ``.pdf``/``.eml``/``.mbox``/
       ``.docx`` so the base pipeline still works for those formats.
    2. For ``.txt`` files (which the base pipeline silently ignores),
       classify by filename prefix and call the appropriate pack
       extractor; convert ``list[Chunk]`` to ``list[Document]``.
    3. For any other suffix or unclassified prefix, behave like the
       base dispatch (returns ``[]``).
    """
    assert _original_dispatch, "pack dispatch called before register()"
    base = _original_dispatch[0](path)
    if base:
        return base
    kind = classify(path)
    if kind is None:
        return base
    if kind == "transcript":
        return _chunks_to_documents(extract_transcript(path), str(path))
    if kind == "pleading":
        return _chunks_to_documents(extract_pleading(path), str(path))
    return base


def register() -> Callable[[Path], list[Document]]:
    """Wire the pack extractors into ``firm_bot.ingest.common.dispatch``.

    Idempotent: calling twice is a no-op the second time. Returns the
    patched dispatch function so tests can introspect it.

    The base dispatch is preserved as ``firm_bot.ingest.common._PACK_ORIGINAL_DISPATCH``
    so :func:`unregister` can restore it. This is purely additive — the
    base dispatch is replaced (not wrapped around) at the module level,
    but only for files the base ignores; PDF/EML/mbox/DOCX continue to
    flow through the original code path.
    """
    pkg = _get_ingest_pkg()
    if _original_dispatch:
        # already registered — return the patched dispatch
        result: Callable[[Path], list[Document]] = pkg.common.dispatch
        return result
    _original_dispatch.append(pkg.common.dispatch)
    # ``_PACK_ORIGINAL_DISPATCH`` is intentionally monkey-patched onto
    # the ``common`` module. mypy can't see it because it's not
    # declared on the module; the suppression keeps strict mode happy.
    pkg.common._PACK_ORIGINAL_DISPATCH = pkg.common.dispatch
    pkg.common.dispatch = _pack_dispatch
    result2: Callable[[Path], list[Document]] = pkg.common.dispatch
    return result2


def _get_ingest_pkg() -> Any:
    """Lazy import of ``firm_bot.ingest`` (three packages up)."""
    from ... import ingest as _ingest_pkg  # noqa: PLC0415

    return _ingest_pkg


def unregister() -> None:
    """Restore the base ``firm_bot.ingest.common.dispatch``.

    Safe to call when the pack is not registered (no-op).
    """
    if not _original_dispatch:
        return
    pkg = _get_ingest_pkg()
    original: Callable[[Path], list[Document]] = _original_dispatch.pop()
    pkg.common.dispatch = original
    if hasattr(pkg.common, "_PACK_ORIGINAL_DISPATCH"):
        del pkg.common._PACK_ORIGINAL_DISPATCH
