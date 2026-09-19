"""Convert CUAD contracts into PDFs for firm-bot ingestion.

Reads ``CUADv1.json``, emits one PDF per contract into
``eval/cuad_corpus/``. Each PDF preserves the original paragraph
boundaries with `\n\n` separators so the structure-aware chunker
has section boundaries to recognise.

Usage:
    python -m eval.build_cuad_corpus --n 10 --out eval/cuad_corpus
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def _download_cuad(target: Path) -> Path:
    if (target / "data_extracted" / "CUADv1.json").exists():
        return target / "data_extracted"
    if (target / "CUADv1.json").exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "https://github.com/TheAtticusProject/cuad.git",
            str(target),
        ],
        check=True,
    )
    subprocess.run(
        ["unzip", "-q", str(target / "data.zip"), "-d", str(target / "data_extracted")],
        check=True,
    )
    return target / "data_extracted"


def _clean(text: str) -> str:
    """Normalise whitespace; CUAD paragraphs are already clean-ish."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build(out_dir: Path, n: int) -> int:
    cache = Path(os.environ.get("FIRM_BOT_CUAD_CACHE", "/tmp/cuad_repo"))
    data_dir = _download_cuad(cache)
    raw = json.loads((data_dir / "CUADv1.json").read_text())
    contracts = raw["data"][:n]
    out_dir.mkdir(parents=True, exist_ok=True)

    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "body", parent=styles["BodyText"], fontSize=9, leading=12, spaceAfter=6
    )
    title_style = ParagraphStyle(
        "title", parent=styles["Heading1"], fontSize=12, leading=14, spaceAfter=8
    )

    for i, c in enumerate(contracts, 1):
        title = c.get("title", f"contract-{i}").strip().replace("/", "_")[:120]
        out = out_dir / f"{title}.pdf"
        doc = SimpleDocTemplate(
            str(out),
            pagesize=LETTER,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )
        flow = [Paragraph(title, title_style), Spacer(1, 6)]
        for para in c.get("paragraphs", []):
            ctx = _clean(para.get("context", ""))
            if not ctx:
                continue
            for chunk in ctx.split("\n\n"):
                flow.append(Paragraph(chunk.replace("\n", " "), body_style))
        doc.build(flow)
    return len(contracts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--out", default="eval/cuad_corpus")
    args = parser.parse_args()
    n = build(Path(args.out), args.n)
    print(f"wrote {n} PDFs to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
