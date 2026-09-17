"""Build a CUAD-style benchmark fixture.

CUAD (Contract Understanding Atticus Dataset) is the industry-standard
benchmark for legal contract QA — 510 contracts with 13k+ labeled clause
regions across 41 clause categories. We use a SUBSET of CUAD to produce
a fixture in the same shape as our synthetic one, so the same eval
harness (`eval.compare`, `eval.eval_e2e`) can run against it.

Usage:
    python -m eval.build_cuad_benchmark --out eval/cuad_fixture.json --n-contracts 10

The output is a JSON fixture with ``cases`` shaped like::

    {
      "question": "What's the cap on liability?",
      "expected_source": "LIMEENERGYCO_..._EX-10-DISTRIBUTOR AGREEMENT.pdf",
      "expected_keywords": ["<phrase from the labeled answer>"]
    }

CUAD's data files come from GitHub: https://github.com/TheAtticusProject/cuad
This script downloads them if missing; otherwise uses a local copy.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

# A mapping from CUAD clause category ids to natural-language questions.
# We pick a subset of categories that produce useful questions for RAG.
CUAD_CATEGORIES: dict[str, str] = {
    "Cap on Liability": "What's the cap on liability?",
    "Indemnification": "What are the indemnification obligations?",
    "Termination for Convenience": "Can this contract be terminated for convenience?",
    "Change of Control": "What happens on a change of control?",
    "Anti-Assignment": "Can the contract be assigned to a third party?",
    "Revenue/Profit Sharing": "Is there a revenue or profit share?",
    "Audit Rights": "Does either party have audit rights?",
    "Governing Law": "What is the governing law?",
    "Non-Compete": "Is there a non-compete clause?",
    "Exclusivity": "Is there an exclusivity provision?",
    "No-Solicit Of Customers": "Is solicitation of customers restricted?",
    "Competitive Restriction Exception": "Are there exceptions to the non-compete?",
    "Warranty Duration": "How long is the warranty?",
    "Insurance": "What insurance is required?",
    "Covenant Not To Sue": "Is there a covenant not to sue?",
    "Liquidated Damages": "Are there liquidated damages?",
    "Warranty": "What warranties are given?",
    "License Grant": "What license is granted?",
    "Non-Disparagement": "Is non-disparagement required?",
    "Termination For Cause": "When can the contract be terminated for cause?",
}


def _download_cuad(target: Path) -> Path:
    """Clone CUAD into ``target`` if not already present. Returns the data dir."""
    if (target / "data_extracted").exists():
        return target / "data_extracted"
    if (target / "CUADv1.json").exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"cloning CUAD to {target} (one-time)...")
    subprocess.run(
        ["git", "clone", "--depth", "1", "https://github.com/TheAtticusProject/cuad.git", str(target)],
        check=True,
    )
    print("unzipping data.zip...")
    subprocess.run(
        ["unzip", "-q", str(target / "data.zip"), "-d", str(target / "data_extracted")],
        check=True,
    )
    return target / "data_extracted"


def _short_answer(answers: list[dict[str, Any]]) -> str:
    """Pick the first non-empty labeled answer text from a CUAD QA entry."""
    for a in answers:
        raw_text = a.get("text")
        if not raw_text:
            continue
        text = str(raw_text).strip()
        if text and text.lower() != "none":
            return text[:120].rstrip(",.;:")
    return ""


def build(out_path: Path, n_contracts: int = 10, max_per_contract: int = 3) -> dict[str, Any]:
    """Build a CUAD fixture of (question, source, keywords) triples."""
    cache = Path(os.environ.get("FIRM_BOT_CUAD_CACHE", "/tmp/cuad_repo"))
    data_dir = _download_cuad(cache)
    raw = json.loads((data_dir / "CUADv1.json").read_text())
    contracts = raw["data"]

    cases: list[dict[str, Any]] = []
    used_contracts = 0
    seen_questions: set[str] = set()
    for c in contracts:
        if used_contracts >= n_contracts:
            break
        title = c.get("title", "").strip()
        # CUAD titles are long; shorten to a file-like slug
        short_title = title.replace("/", "_")[:120]
        if not short_title:
            continue

        # Take all paragraphs for this contract (usually 1) and walk QAs
        questions_in_contract = 0
        for para in c.get("paragraphs", []):
            for qa in para.get("qas", []):
                qtext = qa.get("question", "").strip()
                if qtext in seen_questions:
                    continue
                # Strip CUAD's "Highlight the parts..." framing down to the
                # clause name by matching against our category table.
                norm = None
                for cat, friendly in CUAD_CATEGORIES.items():
                    if cat in qtext:
                        norm = friendly
                        break
                if norm is None:
                    continue
                kw = _short_answer(qa.get("answers", []))
                if not kw:
                    continue
                seen_questions.add(qtext)
                cases.append({
                    "question": norm,
                    "expected_source": f"{short_title}.pdf",
                    "expected_keywords": [kw],
                })
                questions_in_contract += 1
                if questions_in_contract >= max_per_contract:
                    break
            if questions_in_contract >= max_per_contract:
                break
        used_contracts += 1

    fixture = {"cases": cases, "source": "CUAD (Contract Understanding Atticus Dataset)", "n_contracts": used_contracts}
    out_path.write_text(json.dumps(fixture, indent=2))
    print(f"wrote {out_path} with {len(cases)} cases across {used_contracts} contracts")
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="eval/cuad_fixture.json")
    parser.add_argument("--n-contracts", type=int, default=10)
    parser.add_argument("--max-per-contract", type=int, default=3)
    args = parser.parse_args()
    build(Path(args.out), args.n_contracts, args.max_per_contract)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
