"""Document ingestion for firm-bot.

Three submodules:
- :mod:`firm_bot.ingest.pdf`  — PDFs (text-backed + scanned/OCR)
- :mod:`firm_bot.ingest.eml`  — RFC 822 email (.eml) and mbox files
- :mod:`firm_bot.ingest.docx` — Microsoft Word .docx
- :mod:`firm_bot.ingest.common` — shared dataclasses + per-tenant dispatch

Every extractor returns ``list[Document]`` where each ``Document`` carries:
- ``doc_id`` — stable hash of the file + a per-page/per-message key
- ``text`` — the extracted text
- ``metadata`` — provenance (path, page, message-id, etc.)
"""
from __future__ import annotations

from .common import Document, IngestStats, dispatch
from .docx import extract_docx
from .eml import extract_eml, extract_mbox
from .pdf import extract_pdf

__all__ = [
    "Document",
    "IngestStats",
    "dispatch",
    "extract_docx",
    "extract_eml",
    "extract_mbox",
    "extract_pdf",
]
