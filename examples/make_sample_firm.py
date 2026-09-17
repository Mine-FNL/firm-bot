"""Generate a synthetic contract PDF for the smoke test.

Run from the project root:
    python examples/make_sample_firm.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


def build_pdf(out_path: Path, title: str, sections: list[tuple[str, str]]) -> None:
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, leading=22, spaceAfter=12)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=14, leading=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=11, leading=14, spaceAfter=6)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )
    flow: list = [Paragraph(title, h1), Spacer(1, 12)]
    for heading, body_text in sections:
        flow.append(Paragraph(heading, h2))
        for paragraph in body_text.split("\n\n"):
            flow.append(Paragraph(paragraph.replace("\n", " "), body))
        flow.append(Spacer(1, 6))
    doc.build(flow)


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data/firms/demo/source")
    out_dir.mkdir(parents=True, exist_ok=True)

    build_pdf(
        out_dir / "acme_msa.pdf",
        "Master Services Agreement — Acme Corp / Demo LLP",
        [
            (
                "Article I — Definitions",
                "For the purposes of this Agreement, the following terms shall have the meanings set forth below. "
                "\"Affiliate\" means any entity that directly or indirectly controls, is controlled by, or is under "
                "common control with a party. \"Confidential Information\" means any non-public information disclosed "
                "by one party to the other, whether orally or in writing, that is designated as confidential or that "
                "should reasonably be understood to be confidential given the nature of the information.",
            ),
            (
                "Article II — Services",
                "Demo LLP shall provide professional consulting services as described in one or more Statements of "
                "Work executed by the parties. Each Statement of Work shall set forth the scope of services, "
                "deliverables, timeline, and fees.",
            ),
            (
                "Section 4.2 — Limitation of Liability",
                "EXCEPT FOR BREACHES OF CONFIDENTIALITY OR INDEMNIFICATION OBLIGATIONS, NEITHER PARTY'S AGGREGATE "
                "LIABILITY ARISING OUT OF OR RELATED TO THIS AGREEMENT SHALL EXCEED THE FEES PAID BY ACME CORP TO "
                "DEMO LLP IN THE TWELVE (12) MONTHS PRECEDING THE EVENT GIVING RISE TO THE CLAIM. IN NO EVENT SHALL "
                "EITHER PARTY BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES.",
            ),
            (
                "Section 6.1 — Indemnification by Demo LLP",
                "Demo LLP shall indemnify, defend, and hold harmless Acme Corp from and against any third-party "
                "claims arising out of (a) Demo LLP's gross negligence or wilful misconduct, or (b) any breach of "
                "Demo LLP's confidentiality obligations under Article I.",
            ),
            (
                "Section 8.4 — Termination",
                "Either party may terminate this Agreement for material breach upon thirty (30) days' written "
                "notice if the breach remains uncured at the end of such period. Acme Corp may also terminate any "
                "Statement of Work for convenience upon fifteen (15) days' written notice.",
            ),
            (
                "Schedule A — Fee Schedule",
                "Hourly rates: Senior Partner $650/hour, Partner $475/hour, Senior Associate $325/hour, "
                "Associate $210/hour, Paralegal $125/hour. Fixed fees for routine filings available on request.",
            ),
        ],
    )

    build_pdf(
        out_dir / "nda.pdf",
        "Mutual Non-Disclosure Agreement",
        [
            (
                "Definitions",
                "Confidential Information means information disclosed by either party that is marked confidential "
                "or that a reasonable person would understand to be confidential. The receiving party shall use "
                "Confidential Information only for the Purpose.",
            ),
            (
                "Permitted Disclosures",
                "The receiving party may disclose Confidential Information to its employees, contractors, and "
                "professional advisors who have a need to know and are bound by confidentiality obligations no "
                "less protective than those herein.",
            ),
            (
                "Term",
                "This Agreement shall remain in effect for three (3) years from the Effective Date. "
                "Confidentiality obligations shall survive termination for an additional five (5) years.",
            ),
        ],
    )

    print(json.dumps({"generated": sorted(str(p) for p in out_dir.iterdir())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())