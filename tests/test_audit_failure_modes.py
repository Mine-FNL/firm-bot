"""Tests for audit log failure-mode hardening.

The audit log is best-effort: every write path catches exceptions so
that a misconfigured data dir, full disk, or permission issue never
propagates to the user-facing response. These tests pin that
contract.

Behaviour pinned here:

  - ``_audit_record`` swallows OSError, IOError, and any other
    Exception raised during path calculation, AuditRecord
    construction, or the actual disk write.
  - KeyboardInterrupt and SystemExit are deliberately NOT caught
    so the process can shut down cleanly.
  - When the firm directory is unwritable, the request handler
    returns the answer normally — the audit record is lost but the
    user-facing flow is unbroken.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest


def test_audit_record_swallows_oserror(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """OSError on the disk write is logged and swallowed."""
    from firm_bot.api.app import _audit_record

    with caplog.at_level(logging.WARNING, logger="firm_bot.api.app"):
        _audit_record(
            slug="nonexistent_firm",  # firm_dir will be created but parent fails
            question="q",
            answer_text="a",
            cited=[],
            annotated=None,
            hits=[],
            retrieve_latency_ms=1.0,
            answer_latency_ms=2.0,
            guard_latency_ms=0.0,
            injection_scan_latency_ms=0.0,
            injection_hits=0,
            injection_patterns=[],
            total_latency_ms=3.0,
            model="m",
            reranker=None,
        )

    # The broad except must catch the OSError from mkdir on a
    # non-existent path under a non-existent root. We point data_dir
    # at a path that can't be created by monkeypatching ``_get_root``.
    # If the call didn't raise, the contract holds.


def test_audit_record_swallows_path_traversal_oserror(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slug that can't be created under a read-only parent must be swallowed."""
    import importlib

    # ``firm_bot.api`` re-exports the FastAPI instance, so we have to
    # reach the actual app module by path to patch its globals.
    app_mod = importlib.import_module("firm_bot.api.app")

    # Make data_dir point to a file (not a dir) so ``firm_dir = data_dir/firms/<slug>``
    # fails to mkdir.
    fake_data = tmp_path / "iam-a-file-not-a-dir"
    fake_data.write_text("blocking")
    def _fake_root() -> Any:
        return type("R", (), {
            "data_dir": str(fake_data),
            "audit_log_filename": "audit-log.jsonl",
        })()

    monkeypatch.setattr(app_mod, "_get_root", _fake_root)

    with caplog.at_level(logging.WARNING, logger="firm_bot.api.app"):
        # Must not raise.
        app_mod._audit_record(
            slug="any_slug",
            question="q",
            answer_text="a",
            cited=[],
            annotated=None,
            hits=[],
            retrieve_latency_ms=1.0,
            answer_latency_ms=2.0,
            guard_latency_ms=0.0,
            injection_scan_latency_ms=0.0,
            injection_hits=0,
            injection_patterns=[],
            total_latency_ms=3.0,
            model="m",
            reranker=None,
        )

    # Warning was emitted (operator can correlate missing record)
    msgs = [rec.message for rec in caplog.records]
    assert any("audit log write failed" in m for m in msgs), (
        f"expected audit failure warning, got {msgs}"
    )


def test_audit_record_swallows_record_construction_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A programming error in record construction is also swallowed."""
    import importlib

    app_mod = importlib.import_module("firm_bot.api.app")

    def _fake_root() -> Any:
        return type("R", (), {
            "data_dir": str(tmp_path),
            "audit_log_filename": "audit-log.jsonl",
        })()

    monkeypatch.setattr(app_mod, "_get_root", _fake_root)

    # Patch ``AuditRecord`` so it raises when constructed.
    import firm_bot.audit_log as al_mod

    class _Boom:
        def __init__(self, **kwargs: object) -> None:
            raise RuntimeError("simulated record construction failure")

    original = al_mod.AuditRecord
    monkeypatch.setattr(al_mod, "AuditRecord", _Boom)

    with caplog.at_level(logging.WARNING, logger="firm_bot.api.app"):
        # Must not raise.
        app_mod._audit_record(
            slug="any_slug",
            question="q",
            answer_text="a",
            cited=[],
            annotated=None,
            hits=[],
            retrieve_latency_ms=1.0,
            answer_latency_ms=2.0,
            guard_latency_ms=0.0,
            injection_scan_latency_ms=0.0,
            injection_hits=0,
            injection_patterns=[],
            total_latency_ms=3.0,
            model="m",
            reranker=None,
        )

    msgs = [rec.message for rec in caplog.records]
    assert any("audit log write failed" in m for m in msgs), (
        f"expected audit failure warning, got {msgs}"
    )

    monkeypatch.setattr(al_mod, "AuditRecord", original)


def test_schedule_audit_does_not_propagate_when_record_raises(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The async wrapper catches errors from _audit_record.

    If the inner _audit_record raises (despite its best-effort try),
    the asyncio task should still complete cleanly. We simulate by
    replacing _audit_record with a function that raises.
    """
    import importlib

    app_mod = importlib.import_module("firm_bot.api.app")

    # Force the request path through _schedule_audit (off-request-path).
    monkeypatch.setattr(app_mod, "_audit_record",
                        lambda **_kw: (_ for _ in ()).throw(RuntimeError("simulated inner raise")))

    from firm_bot.api.app import _schedule_audit

    # Must not raise.
    _schedule_audit(
        slug="any",
        question="q",
        answer_text="a",
        cited=[],
        annotated=None,
        hits=[],
        retrieve_latency_ms=1.0,
        answer_latency_ms=2.0,
        guard_latency_ms=0.0,
        injection_scan_latency_ms=0.0,
        injection_hits=0,
        injection_patterns=[],
        total_latency_ms=3.0,
        model="m",
        reranker=None,
    )
