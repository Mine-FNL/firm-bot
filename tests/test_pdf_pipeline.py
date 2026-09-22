"""Tests for the PDF export pipeline.

Verifies the 12 PDFs in ``pdfs/`` actually render correctly:

  - ``pdfinfo`` runs without error
  - ``pdftotext`` extracts the first H1 from the source markdown
    (i.e. the content actually went into the PDF)
  - ``pdftotext`` does NOT contain the "fi rm" / "fl ow" ligature
    artifacts that broke the original Inter-font render — that's
    the regression we're guarding against
  - Page count >= 1
  - File size > 50 KB (sanity: an empty PDF would be a few KB)

These run via ``python3 scripts/render_pdf.py`` for each source if a
``--regenerate`` flag is passed; otherwise they verify the committed
PDFs directly. CI should regenerate before measuring.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PDFS_DIR = ROOT / "pdfs"

# The distribution pack — every entry must have BOTH a source
# markdown at repo root AND a generated PDF in pdfs/.
SOURCES: list[str] = [
    "WHITEPAPER.md",
    "INVESTORS.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "ARTICLE_BLOG.md",
    "ARTICLE_DEVTO.md",
    "INDIE_HACKERS.md",
    "PRODUCT_HUNT.md",
    "LAUNCH.md",
    "SHOWCASE.md",
    "OUTREACH.md",
    "README.md",
]


def _require_tools() -> None:
    """Skip the whole module if poppler tools are missing."""
    for tool in ("pdfinfo", "pdftotext"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not on PATH; install poppler")


@pytest.fixture(scope="module", autouse=True)
def _tools_present() -> None:
    _require_tools()


def _first_h1(md_path: Path) -> str:
    """Return the first H1 line from the markdown source, stripped."""
    for line in md_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return md_path.stem


def _pdfinfo_field(pdf_path: Path, field: str) -> str:
    proc = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, f"pdfinfo failed for {pdf_path}:\n{proc.stderr}"
    for line in proc.stdout.splitlines():
        if line.startswith(f"{field}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _pdftotext(pdf_path: Path) -> str:
    proc = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, f"pdftotext failed for {pdf_path}:\n{proc.stderr}"
    return proc.stdout


# ---- per-PDF checks ---------------------------------------------------


@pytest.mark.parametrize("src_name", SOURCES)
def test_pdf_exists(src_name: str) -> None:
    """Each source markdown has a matching PDF in pdfs/."""
    pdf_path = PDFS_DIR / src_name.replace(".md", ".pdf")
    assert pdf_path.exists(), f"missing PDF for {src_name}: {pdf_path}"


@pytest.mark.parametrize("src_name", SOURCES)
def test_pdf_pages_at_least_one(src_name: str) -> None:
    pdf_path = PDFS_DIR / src_name.replace(".md", ".pdf")
    pages = _pdfinfo_field(pdf_path, "Pages")
    assert pages.isdigit(), f"non-numeric Pages value: {pages!r}"
    assert int(pages) >= 1


@pytest.mark.parametrize("src_name", SOURCES)
def test_pdf_size_above_threshold(src_name: str) -> None:
    """An empty/blank PDF would be ~2 KB. Real content is >50 KB."""
    pdf_path = PDFS_DIR / src_name.replace(".md", ".pdf")
    size = pdf_path.stat().st_size
    assert size > 50_000, f"{pdf_path.name} is {size} bytes — too small to be real"


@pytest.mark.parametrize("src_name", SOURCES)
def test_pdf_contains_source_h1(src_name: str) -> None:
    """The PDF must contain the first H1 from the source markdown."""
    md_path = ROOT / src_name
    pdf_path = PDFS_DIR / src_name.replace(".md", ".pdf")
    expected_h1 = _first_h1(md_path)
    assert expected_h1, f"no H1 in {src_name}"
    text = _pdftotext(pdf_path)
    # Strip whitespace and squashed whitespace for robust matching;
    # Chromium's text layer can introduce line breaks in the middle
    # of a heading.
    normalized = re.sub(r"\s+", " ", text)
    assert expected_h1 in normalized, (
        f"{pdf_path.name} is missing H1 {expected_h1!r}\n"
        f"  first 200 chars of extracted text: {normalized[:200]!r}"
    )


@pytest.mark.parametrize("src_name", SOURCES)
def test_pdf_no_ligature_breakage(src_name: str) -> None:
    """Regression guard: the rendered text must NOT contain 'fi rm' / 'fl ow'.

    Earlier versions of pdf-style.css asked for Inter / JetBrains Mono
    which weren't installed, causing Chromium's fallback font to break
    the 'fi' and 'fl' ligatures into visible two-character sequences.
    We switched to system fonts + explicit ``font-feature-settings``
    disable — this test ensures we don't regress.
    """
    pdf_path = PDFS_DIR / src_name.replace(".md", ".pdf")
    text = _pdftotext(pdf_path)
    # Use word boundaries: 'fi rm' should not appear as a standalone
    # token. We allow 'fi rm' inside normal words like 'firmware' but
    # catch the artifact where it appears between spaces in what
    # should be 'firm'.
    artifacts = [
        # 'fi rm' inside what should be 'firm' (common broken word)
        (r"\bfi\s+rm\b", "fi+rm broken ligature"),
        # 'fl ow' inside what should be 'flow' / 'flowing'
        (r"\bfl\s+ow\b", "fl+ow broken ligature"),
        # 'fi ght' inside 'fight'
        (r"\bfi\s+ght\b", "fi+ght broken ligature"),
        # 'fl exibility' inside 'flexibility'
        (r"\bfl\s+exibility\b", "fl+exibility broken ligature"),
    ]
    failures: list[str] = []
    for pattern, label in artifacts:
        m = re.search(pattern, text)
        if m:
            failures.append(f"{label}: {m.group(0)!r}")
    assert not failures, f"{pdf_path.name} has ligature artifacts:\n  " + "\n  ".join(failures)


@pytest.mark.parametrize("src_name", SOURCES)
def test_pdf_has_letter_size_pages(src_name: str) -> None:
    """All PDFs render on Letter (8.5x11 inches = 612x792 pts).

    Catches accidental A4 rendering or other sizing regressions.
    """
    pdf_path = PDFS_DIR / src_name.replace(".md", ".pdf")
    page_size = _pdfinfo_field(pdf_path, "Page size")
    assert "612" in page_size and "792" in page_size, (
        f"{pdf_path.name} expected Letter (612x792 pts), got {page_size!r}"
    )


# ---- pipeline integrity ----------------------------------------------


def test_pdf_style_css_exists() -> None:
    """The CSS that drives the render must be present at repo root."""
    css = ROOT / "pdf-style.css"
    assert css.exists(), f"missing {css}"
    text = css.read_text(encoding="utf-8")
    # Regression guards: the CSS must not request Inter / JetBrains
    # Mono in any ``font-family`` rule (those fonts are not installed
    # locally and cause ligature breakage). Use a regex anchored to
    # the property so the warning text in the comment block is
    # ignored — only an actual CSS rule triggers the failure.
    bad_font_refs = re.findall(
        r"font-family\s*:\s*[^;]*?(Inter|JetBrains Mono)[^;]*?;",
        text,
    )
    assert not bad_font_refs, (
        f"pdf-style.css has font-family rule(s) requesting "
        f"{bad_font_refs!r} — these fonts aren't installed locally "
        f"and trigger ligature breakage"
    )
    # And must explicitly disable ligatures for safety.
    assert "font-feature-settings" in text, (
        "pdf-style.css missing 'font-feature-settings' rule — without it "
        "Chromium can re-enable ligatures via fallback fonts"
    )


def test_render_script_exists() -> None:
    """scripts/render_pdf.py is the documented regeneration tool."""
    script = ROOT / "scripts" / "render_pdf.py"
    assert script.exists(), f"missing {script}"
    text = script.read_text(encoding="utf-8")
    # Must invoke pandoc + playwright so the pipeline is reproducible.
    assert "pandoc" in text
    assert "playwright" in text
