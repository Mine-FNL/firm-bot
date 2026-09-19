"""PDF extraction for firm-bot.

Strategy:
1. Try ``pypdf`` to extract text. If a page yields meaningful text, keep it.
2. For pages where pypdf returns < 32 chars (likely scanned / image-only),
   fall back to OCR with Tesseract.

The OCR fallback is gated by ``--ocr/--no-ocr`` and by per-document page
count: contracts scanned at 600 dpi can produce 1000+ pages and burn
hours of OCR. We cap at 25 OCR pages per file by default (configurable
via env ``FIRM_BOT_OCR_PAGES``), and emit a warning when we hit the cap.

The hybrid heuristic mirrors what Falcon Nest's ``document_ingestion.py``
does — selectable headers/footers do NOT count as "text-backed" because
poppler can fabricate them. We use a stricter word-count threshold.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .common import Document, stable_doc_id

log = logging.getLogger("firm_bot.ingest.pdf")

# Below this many alphabetic words, the page is considered image-only.
PAGE_TEXT_MIN_WORDS = 32
MAX_OCR_PAGES = int(os.environ.get("FIRM_BOT_OCR_PAGES", "25"))


def _page_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z]{2,}", text))


def _ocr_page(pdf_path: Path, page_index: int) -> str:
    """Render one page to an image and OCR it."""
    import pytesseract
    from pdf2image import convert_from_path  # optional dep

    images = convert_from_path(
        str(pdf_path),
        first_page=page_index + 1,
        last_page=page_index + 1,
        dpi=200,
    )
    if not images:
        return ""
    result: str = pytesseract.image_to_string(images[0])
    return result


def extract_pdf(path: Path) -> list[Document]:
    """Extract a PDF into one Document per page.

    Empty pages are dropped. Pages that need OCR but fall outside the
    page cap are dropped with a logged note — the operator should split
    the document or raise the cap.
    """
    out: list[Document] = []
    try:
        reader = PdfReader(str(path))
    except (PdfReadError, OSError) as e:
        log.warning("pdf open failed %s: %s", path, e)
        return out

    ocr_used = 0
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as e:  # pypdf can throw on weird encodings
            log.debug("pypdf page %d of %s failed: %s", i + 1, path, e)
            text = ""

        # Some pypdf builds can return a noisy single character; the word
        # count is the right discriminator.
        if _page_words(text) >= PAGE_TEXT_MIN_WORDS:
            out.append(
                Document(
                    doc_id=stable_doc_id(str(path), f"page-{i + 1}"),
                    text=_clean(text),
                    metadata={
                        "source_path": str(path),
                        "source_name": path.name,
                        "page": i + 1,
                        "page_count": len(reader.pages),
                        "extractor": "pypdf",
                    },
                )
            )
            continue

        # OCR fallback path
        if ocr_used >= MAX_OCR_PAGES:
            log.warning(
                "OCR cap (%d) reached for %s, page %d skipped",
                MAX_OCR_PAGES,
                path,
                i + 1,
            )
            continue
        try:
            ocr_text = _ocr_page(path, i)
        except Exception as e:
            log.debug("OCR page %d of %s failed: %s", i + 1, path, e)
            continue
        ocr_used += 1
        if _page_words(ocr_text) >= PAGE_TEXT_MIN_WORDS:
            out.append(
                Document(
                    doc_id=stable_doc_id(str(path), f"page-{i + 1}"),
                    text=_clean(ocr_text),
                    metadata={
                        "source_path": str(path),
                        "source_name": path.name,
                        "page": i + 1,
                        "page_count": len(reader.pages),
                        "extractor": "ocr",
                    },
                )
            )
    return out


_WS = re.compile(r"[ \t]+")
_NL = re.compile(r"\n{3,}")


def _clean(text: str) -> str:
    """Normalise whitespace; preserve paragraph structure."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    text = _NL.sub("\n\n", text)
    return text.strip()
