"""Tests for the regression-detection mode of `eval.compare`.

Exercises `--check-regression`: given two JSON reports, exits 0 on no
regression and 1 on a regression beyond the threshold.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.compare import _check_regression


def _write_report(
    path: Path,
    *,
    firm_bot: float,
    naive: float,
    firm_bot_rerank: float | None = None,
) -> None:
    """Write a minimal benchmark JSON in the shape eval.compare emits."""
    data: dict[str, dict[str, float]] = {
        "mean_precision_at_k": {"firm_bot": firm_bot, "naive": naive},
    }
    if firm_bot_rerank is not None:
        data["mean_precision_at_k"]["firm_bot_rerank"] = firm_bot_rerank
    path.write_text(json.dumps(data), encoding="utf-8")


def test_check_regression_no_regression(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_report(baseline, firm_bot=0.62, naive=0.61)
    _write_report(current, firm_bot=0.62, naive=0.61)
    rc = _check_regression(baseline, current, max_regression_pct=5.0)
    assert rc == 0


def test_check_regression_small_drop_within_threshold(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_report(baseline, firm_bot=0.62, naive=0.61)
    _write_report(current, firm_bot=0.60, naive=0.61)  # -2pp — within 5pp
    rc = _check_regression(baseline, current, max_regression_pct=5.0)
    assert rc == 0


def test_check_regression_large_drop_exits_1(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_report(baseline, firm_bot=0.80, naive=0.61)
    _write_report(current, firm_bot=0.62, naive=0.61)  # -18pp
    rc = _check_regression(baseline, current, max_regression_pct=5.0)
    assert rc == 1


def test_check_regression_per_chunker_threshold(tmp_path: Path) -> None:
    """Only the regressing chunker triggers; the other stays fine."""
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_report(baseline, firm_bot=0.80, naive=0.61)
    _write_report(current, firm_bot=0.62, naive=0.61)  # firm_bot -18pp
    rc = _check_regression(baseline, current, max_regression_pct=5.0)
    assert rc == 1  # overall failure due to firm_bot regression


def test_check_regression_improvement_is_not_regression(tmp_path: Path) -> None:
    """If current is better than baseline, that's not a regression."""
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    _write_report(baseline, firm_bot=0.50, naive=0.61)
    _write_report(current, firm_bot=0.62, naive=0.61)  # +12pp improvement
    rc = _check_regression(baseline, current, max_regression_pct=5.0)
    assert rc == 0


def test_check_regression_missing_baseline_returns_2(tmp_path: Path) -> None:
    baseline = tmp_path / "missing.json"
    current = tmp_path / "current.json"
    _write_report(current, firm_bot=0.5, naive=0.5)
    rc = _check_regression(baseline, current, max_regression_pct=5.0)
    assert rc == 2


def test_check_regression_missing_current_returns_2(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "missing.json"
    _write_report(baseline, firm_bot=0.5, naive=0.5)
    rc = _check_regression(baseline, current, max_regression_pct=5.0)
    assert rc == 2


def test_check_regression_missing_section_returns_2(tmp_path: Path) -> None:
    """A report without mean_precision_at_k is malformed."""
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    baseline.write_text(json.dumps({"other_field": 1.0}), encoding="utf-8")
    current.write_text(json.dumps({"mean_precision_at_k": {"firm_bot": 0.5}}), encoding="utf-8")
    rc = _check_regression(baseline, current, max_regression_pct=5.0)
    assert rc == 2
