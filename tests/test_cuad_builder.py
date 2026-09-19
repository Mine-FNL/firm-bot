"""Tests for the CUAD benchmark builder."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_short_answer_returns_first_non_empty() -> None:
    from eval.build_cuad_benchmark import _short_answer

    assert _short_answer([{"text": "  hello world  "}]) == "hello world"
    assert _short_answer([{"text": ""}, {"text": "second"}]) == "second"
    assert _short_answer([]) == ""
    assert _short_answer([{"text": None}]) == ""


def test_short_answer_truncates_long_answers() -> None:
    from eval.build_cuad_benchmark import _short_answer

    long = "x" * 500
    out = _short_answer([{"text": long}])
    assert len(out) <= 120


def test_cuad_categories_table_is_non_empty() -> None:
    """The category mapping covers the most common CUAD question types."""
    from eval.build_cuad_benchmark import CUAD_CATEGORIES

    assert len(CUAD_CATEGORIES) >= 10
    assert "Cap on Liability" in CUAD_CATEGORIES
    assert "Indemnification" in CUAD_CATEGORIES


def test_build_cuad_benchmark_writes_fixture(tmp_path: Path) -> None:
    """End-to-end: build a fixture from a cached CUAD snapshot."""
    cache = Path("/tmp/cuad_repo")
    if not (cache / "data_extracted" / "CUADv1.json").exists():
        pytest.skip("CUAD snapshot not present; skipped")

    from eval.build_cuad_benchmark import build

    out = tmp_path / "cuad.json"
    fixture = build(out, n_contracts=3, max_per_contract=2)
    assert out.exists()
    assert fixture["n_contracts"] == 3
    assert len(fixture["cases"]) > 0
    # every case has the expected shape
    for c in fixture["cases"]:
        assert "question" in c
        assert "expected_source" in c
        assert "expected_keywords" in c and len(c["expected_keywords"]) >= 1


def test_build_cuad_corpus_writes_pdfs(tmp_path: Path) -> None:
    """End-to-end: convert CUAD contracts to PDFs."""
    cache = Path("/tmp/cuad_repo")
    if not (cache / "data_extracted" / "CUADv1.json").exists():
        pytest.skip("CUAD snapshot not present; skipped")

    from eval.build_cuad_corpus import build

    out_dir = tmp_path / "corpus"
    n = build(out_dir, n=2)
    assert n == 2
    pdfs = list(out_dir.glob("*.pdf"))
    assert len(pdfs) == 2
    # PDFs are non-empty (sanity check)
    for p in pdfs:
        assert p.stat().st_size > 1000  # at least 1 KB
