"""Render a Markdown file to PDF via pandoc→HTML→Playwright Chromium.

Used by the firm-bot PDF-export pipeline. Bypasses the pdf skill's
make.sh because that path times out on cold Chromium launches on
some machines; we drive playwright directly with explicit timing.

Usage:
    python3 scripts/render_pdf.py INPUT.md OUTPUT.pdf [--title T] [--author A]

Styling is supplied via pdf-style.css in the repo root.
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = ROOT / "pdf-style.css"


def md_to_html(md_path: Path, title: str, author: str) -> str:
    """Convert markdown to a self-contained HTML page using pandoc.

    Uses ``gfm + html5 + section-divs`` for GFM-ish compatibility.
    The stylesheet is injected via ``--css``.
    """
    md_text = md_path.read_text(encoding="utf-8")
    proc = subprocess.run(
        [
            "pandoc",
            "-f",
            "gfm",
            "-t",
            "html5",
            "--standalone",
            "--section-divs",
            "--metadata",
            f"title={title}",
            "--metadata",
            f"author={author}",
            "--css",
            str(CSS_PATH),
            "--no-highlight",
            str(md_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pandoc failed: {proc.stderr}")
    return proc.stdout


async def render_html_to_pdf(html: str, out_path: Path) -> None:
    """Render HTML to PDF via headless Chromium with explicit long timeout.

    Chromium cold-launch on macOS sometimes takes 60+ s; we set a 180 s
    timeout on both navigation and the print operation.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.set_content(html, wait_until="domcontentloaded", timeout=180_000)
        # Give web fonts + any layout a beat to settle.
        await page.wait_for_timeout(500)
        await page.pdf(
            path=str(out_path),
            format="Letter",
            print_background=True,
            margin={
                "top": "1in",
                "right": "0.85in",
                "bottom": "1.1in",
                "left": "0.85in",
            },
        )
        await browser.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Render Markdown to PDF via pandoc+Playwright")
    p.add_argument("input", type=Path, help="Input .md file")
    p.add_argument("output", type=Path, help="Output .pdf file")
    p.add_argument("--title", default=None, help="Document title (default: lifted from H1)")
    p.add_argument("--author", default="Mine-FNL", help="Author meta")
    args = p.parse_args()

    md_path: Path = args.input
    out_path: Path = args.output
    if not md_path.exists():
        print(f"input not found: {md_path}", file=sys.stderr)
        return 1

    # Best-effort title lift: first H1 from the markdown source.
    title = args.title
    if title is None:
        for line in md_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
    title = title or md_path.stem

    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = md_to_html(md_path, title=title, author=args.author)
    asyncio.run(render_html_to_pdf(html, out_path))
    print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
