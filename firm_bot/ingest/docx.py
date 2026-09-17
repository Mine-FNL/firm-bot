"""DOCX extraction for firm-bot.

DOCX is a zip; the text lives in ``word/document.xml``. We use
``python-docx`` because it preserves heading structure — which is the
natural unit of chunking for contracts and policy documents.

Each top-level heading (``Heading 1``) starts a new section. We emit one
``Document`` per section so a chunk carries its heading context in
metadata, not just raw text.
"""
from __future__ import annotations

import logging
from pathlib import Path

from docx import Document as DocxFile

from .common import Document, stable_doc_id

log = logging.getLogger("firm_bot.ingest.docx")


def extract_docx(path: Path) -> list[Document]:
    try:
        doc = DocxFile(str(path))
    except Exception as e:
        log.warning("docx open failed %s: %s", path, e)
        return []

    out: list[Document] = []
    section_idx = 0
    current_heading = "(top)"
    current_paragraphs: list[str] = []

    def _flush() -> None:
        nonlocal section_idx, current_paragraphs
        text = "\n\n".join(p for p in current_paragraphs if p.strip()).strip()
        if text:
            out.append(
                Document(
                    doc_id=stable_doc_id(str(path), f"section-{section_idx}"),
                    text=text,
                    metadata={
                        "source_path": str(path),
                        "source_name": path.name,
                        "section": section_idx,
                        "heading": current_heading,
                        "extractor": "docx",
                    },
                )
            )
        section_idx += 1
        current_paragraphs = []

    for para in doc.paragraphs:
        style_name = para.style.name if para.style else ""
        if style_name.startswith("Heading 1") or style_name == "Title":
            _flush()
            current_heading = para.text.strip() or "(untitled section)"
            continue
        current_paragraphs.append(para.text)
    _flush()
    return out
