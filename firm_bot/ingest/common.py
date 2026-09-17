"""Shared dataclasses for ingestion.

A ``Document`` is one unit that flows into the chunker → embedder → store.
For PDFs we emit one ``Document`` per page so the retriever can cite the
exact page a chunk came from. For email we emit one ``Document`` per
message (sender / subject / date / body stitched together) so the
retriever can cite the message-id. For DOCX we emit one ``Document`` per
section (heading-driven).

The dispatch table maps a path's suffix to the right extractor. We
import the extractors lazily inside ``dispatch`` to avoid a circular
import (``pdf.py`` -> ``common.py`` -> ``pdf.py``).
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_SUFFIXES = {".pdf", ".eml", ".mbox", ".docx"}


@dataclass
class Document:
    """One unit of extracted text."""
    doc_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class IngestStats:
    files_total: int = 0
    files_failed: int = 0
    documents_total: int = 0
    pages_with_ocr: int = 0
    pages_skipped_empty: int = 0
    files_skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def stable_doc_id(*parts: str) -> str:
    """Stable, content-addressed doc_id from arbitrary string parts."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8", errors="replace"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def dispatch(path: Path) -> list[Document]:
    """Pick the right extractor by suffix.

    Unknown suffixes return []; the caller counts these as failures but
    does not raise — an operator may drop a stray file in a firm's
    ``source/`` and we should be graceful about it. Imports are lazy
    to break the ``common.py`` ↔ ``pdf.py`` cycle.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from .pdf import extract_pdf
        return extract_pdf(path)
    if suffix == ".eml":
        from .eml import extract_eml
        return extract_eml(path)
    if suffix == ".mbox":
        from .eml import extract_mbox
        return extract_mbox(path)
    if suffix == ".docx":
        from .docx import extract_docx
        return extract_docx(path)
    return []


def walk_source_dir(source_dir: Path) -> Iterable[Path]:
    """Yield supported files under a firm's source/ directory.

    Hidden files and dirs are skipped. Symlinks are not followed (avoid
    loops). Files outside the supported suffix set are silently filtered.
    """
    if not source_dir.exists():
        return
    for root, dirs, files in os.walk(source_dir, followlinks=False):
        # filter hidden directories in place so os.walk skips them
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in sorted(files):
            if fname.startswith("."):
                continue
            p = Path(root) / fname
            if p.suffix.lower() in SUPPORTED_SUFFIXES:
                yield p


def mime_for(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"
