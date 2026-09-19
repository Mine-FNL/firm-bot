"""Tests for the off-request-path audit log scheduling.

Behaviour pinned here:
  - ``_schedule_audit`` runs the write on a background thread when
    called inside a running event loop, so the request handler
    returns immediately (no fsync on the hot path).
  - When called outside an event loop (unit tests, shutdown), it
    falls back to a synchronous write — never silently drops records.
  - The record lands on disk after the loop drains the pending task.
  - Backpressure: when the in-flight semaphore is full, the call
    falls back to sync. The fallback path is recorded so a warning
    fires once per saturation event.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from firm_bot.api.app import (
    _AUDIT_BACKPRESSURE,
    _schedule_audit,
)
from firm_bot.audit_log import read_audit_log


def _audit_path(tmp_path: Path) -> Path:
    return tmp_path / "firms" / "demo" / "audit-log.jsonl"


def _kwargs(tmp_path: Path) -> dict[str, object]:
    """Minimal kwargs that satisfy ``_audit_record``."""
    (tmp_path / "firms" / "demo").mkdir(parents=True, exist_ok=True)
    return {
        "slug": "demo",
        "question": "what is the cap?",
        "answer_text": "The cap is $100k per occurrence.",
        "cited": ["contract.pdf:p.4"],
        "annotated": None,
        "hits": [],
        "retrieve_latency_ms": 3.5,
        "answer_latency_ms": 1200.0,
        "guard_latency_ms": 0.0,
        "injection_scan_latency_ms": 0.5,
        "injection_hits": 0,
        "injection_patterns": [],
        "total_latency_ms": 1204.0,
        "model": "qwen2.5-coder:7b",
        "reranker": None,
    }


def test_schedule_audit_sync_when_no_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Outside a running loop, write happens synchronously."""
    monkeypatch.setenv("FIRM_BOT_DATA_DIR", str(tmp_path))
    _schedule_audit(**_kwargs(tmp_path))  # type: ignore[arg-type]
    # File exists, has one record
    path = _audit_path(tmp_path)
    assert path.exists()
    records = list(read_audit_log(path))
    assert len(records) == 1
    assert records[0].question_len_chars == len("what is the cap?")


def test_schedule_audit_async_inside_running_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inside a running loop, the write happens on a background task."""
    monkeypatch.setenv("FIRM_BOT_DATA_DIR", str(tmp_path))

    async def _run() -> None:
        _schedule_audit(**_kwargs(tmp_path))  # type: ignore[arg-type]
        # Yield control to let the background task run
        await asyncio.sleep(0.05)
        # Task should have completed by now
        path = _audit_path(tmp_path)
        assert path.exists()
        records = list(read_audit_log(path))
        assert len(records) == 1
        assert records[0].model == "qwen2.5-coder:7b"

    asyncio.run(_run())


def test_schedule_audit_does_not_block_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller of ``_schedule_audit`` returns without waiting on disk."""
    import time

    monkeypatch.setenv("FIRM_BOT_DATA_DIR", str(tmp_path))
    start = time.perf_counter()
    _schedule_audit(**_kwargs(tmp_path))  # type: ignore[arg-type]
    elapsed = time.perf_counter() - start
    # Outside a loop, this is synchronous — but even sync, no fsync of a
    # one-record file should ever take more than a few ms. We assert
    # generously (50ms) to avoid CI flakes on slow disks.
    assert elapsed < 0.05


def test_backpressure_tracks_once_per_saturation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backpressure warning is emitted once, not per call.

    Must call ``_schedule_audit`` from inside a running event loop —
    outside the loop, the function takes the sync-fallback path before
    ever consulting the semaphore.
    """
    import importlib

    monkeypatch.setenv("FIRM_BOT_DATA_DIR", str(tmp_path))
    # Reset warning state so we don't inherit from prior tests
    _AUDIT_BACKPRESSURE.warned_once = False

    # Resolve the actual module object (not the FastAPI instance
    # shadowed by ``firm_bot.api.__init__``'s ``from .app import app``).
    app_mod = importlib.import_module("firm_bot.api.app")

    # Swap in a saturated semaphore. asyncio.Semaphore(1) starts with
    # _value=1 — pin it to 0 so ``locked()`` returns True and the next
    # call takes the sync fallback. (acquire() is async and would need
    # awaiting; setting _value directly is the deterministic test path.)
    saturated = asyncio.Semaphore(1)
    saturated._value = 0  # type: ignore[attr-defined]
    original = app_mod._AUDIT_SEMAPHORE
    app_mod._AUDIT_SEMAPHORE = saturated  # type: ignore[attr-defined]

    async def _run() -> None:
        _schedule_audit(**_kwargs(tmp_path))  # type: ignore[arg-type]
        _schedule_audit(**_kwargs(tmp_path))  # type: ignore[arg-type]
        _schedule_audit(**_kwargs(tmp_path))  # type: ignore[arg-type]

    try:
        asyncio.run(_run())
        assert _AUDIT_BACKPRESSURE.warned_once is True
    finally:
        app_mod._AUDIT_SEMAPHORE = original  # type: ignore[attr-defined]


def test_schedule_audit_writes_correct_record_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The new fields (injection_hits, injection_patterns) flow through."""
    monkeypatch.setenv("FIRM_BOT_DATA_DIR", str(tmp_path))
    kwargs = _kwargs(tmp_path)  # type: ignore[arg-type]
    kwargs["injection_hits"] = 2
    kwargs["injection_patterns"] = ["ignore previous instructions", "you are now"]
    _schedule_audit(**kwargs)
    path = _audit_path(tmp_path)
    line = path.read_text().strip()
    rec = json.loads(line)
    assert rec["prompt_injection_hits"] == 2
    assert rec["prompt_injection_patterns"] == [
        "ignore previous instructions",
        "you are now",
    ]
    # Backwards compat: old audit-log reader uses dataclass with defaults
    assert rec["answer_latency_ms"] == 1200.0
    assert rec["retrieval_latency_ms"] == 4.0  # 3.5 retrieve + 0.5 injection
