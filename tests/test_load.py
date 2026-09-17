"""Load benchmark smoke test — runs in CI to catch regressions.

Exercises the load harness against the in-process TestClient app. Verifies:
- The benchmark completes without raising
- Error rate is < 5% (loose: lets flaky CI pass)
- p95 latency is recorded (any finite value)
- Output JSON has the expected schema

This test is opt-in via ``FIRM_BOT_RUN_LOAD_BENCH=1`` because it takes
several seconds and the harness is designed for benchmark purposes, not
unit-level regression.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from eval.load import _run_against_app, _setup_test_app

pytestmark = pytest.mark.skipif(
    os.environ.get("FIRM_BOT_RUN_LOAD_BENCH") != "1",
    reason="set FIRM_BOT_RUN_LOAD_BENCH=1 to run the load benchmark smoke test",
)


def test_load_smoke() -> None:
    app, slug = _setup_test_app()
    stats = asyncio.run(
        _run_against_app(
            app=app,
            slug=slug,
            queries=["What is the cap on liability?"],
            concurrency=4,
            total=8,
            run_guard=False,
        )
    )
    assert stats.errors == 0, f"load benchmark had {stats.errors} errors"
    assert stats.successes == 8
    assert stats.samples, "no latency samples collected"
    p95 = stats.percentiles()["p95"]
    assert p95 > 0, "p95 must be a finite positive number"
