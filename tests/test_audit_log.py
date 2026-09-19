"""Tests for firm_bot.audit_log."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from firm_bot.audit_log import (
    AuditRecord,
    append_record,
    audit_log_path,
    hash_api_key,
    hash_text,
    prune_older_than,
    read_audit_log,
    request_id_now,
    to_csv,
    to_json,
    to_jsonl,
    to_markdown,
    utc_now_iso,
)

# ---- helpers ----


def _make_record(
    *,
    ts: str = "2026-09-19T10:00:00.000Z",
    request_id: str = "01900000-0000-7000-8000-000000000001",
    firm_slug: str = "demo",
    question: str = "What's the cap on liability?",
    answer: str = "Twelve months of fees paid.",
    guard_summary: str = "ok",
    guard_issue_count: int = 0,
    confidence: float = 0.85,
    model: str = "qwen2.5-coder:7b",
    retrieval_latency_ms: float = 12.5,
    answer_latency_ms: float = 0.0,
    total_latency_ms: float = 12.5,
    hit_count: int = 6,
    reranker: str | None = None,
    api_key_hash: str | None = None,
) -> AuditRecord:
    return AuditRecord(
        timestamp=ts,
        request_id=request_id,
        firm_slug=firm_slug,
        question_hash=hash_text(question),
        question_len_chars=len(question),
        answer_len_chars=len(answer),
        citation_count=1,
        guard_summary=guard_summary,
        guard_issue_count=guard_issue_count,
        confidence=confidence,
        model=model,
        retrieval_latency_ms=retrieval_latency_ms,
        answer_latency_ms=answer_latency_ms,
        total_latency_ms=total_latency_ms,
        hit_count=hit_count,
        reranker=reranker,
        api_key_hash=api_key_hash,
    )


@pytest.fixture
def firm_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data" / "firms" / "demo"
    d.mkdir(parents=True)
    return d


# ---- hashing helpers ----


def test_hash_text_is_stable_short_and_distinguishing() -> None:
    a = hash_text("What is the cap?")
    b = hash_text("What is the cap?")
    c = hash_text("What is the CAP?")
    assert a == b
    assert a != c
    assert len(a) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", a) is not None


def test_hash_api_key_none_passthrough() -> None:
    assert hash_api_key(None) is None
    assert hash_api_key("") is None


def test_hash_api_key_short_and_distinguishing() -> None:
    h1 = hash_api_key("k1")
    h2 = hash_api_key("k2")
    assert len(h1) == 12
    assert h1 != h2


# ---- append + read ----


def test_append_creates_file_and_writes_one_line(firm_dir: Path) -> None:
    path = audit_log_path(firm_dir)
    assert not path.exists()
    append_record(path, _make_record())
    assert path.exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["firm_slug"] == "demo"


def test_append_multiple_records_all_parseable(firm_dir: Path) -> None:
    path = audit_log_path(firm_dir)
    for i in range(5):
        append_record(path, _make_record(request_id=f"req-{i:03d}"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    for i, line in enumerate(lines):
        parsed = json.loads(line)
        assert parsed["request_id"] == f"req-{i:03d}"


def test_read_audit_log_returns_records(firm_dir: Path) -> None:
    path = audit_log_path(firm_dir)
    for i in range(3):
        append_record(path, _make_record(request_id=f"r-{i}"))
    records = list(read_audit_log(path))
    assert len(records) == 3


def test_read_audit_log_skips_malformed_lines(firm_dir: Path) -> None:
    path = audit_log_path(firm_dir)
    append_record(path, _make_record())
    path.write_text(path.read_text() + "\nthis is not json\n", encoding="utf-8")
    append_record(path, _make_record(request_id="after-bad"))
    records = list(read_audit_log(path))
    # The malformed line is skipped, but the two good records are kept.
    assert len(records) == 2
    assert records[0].request_id != "after-bad"
    assert records[1].request_id == "after-bad"


def test_read_audit_log_skips_wrong_shape(firm_dir: Path) -> None:
    """A record with an extra field should not crash the reader."""
    path = audit_log_path(firm_dir)
    append_record(path, _make_record())
    # Append a JSON line that's parseable but doesn't match the dataclass.
    path.write_text(
        path.read_text() + '\n{"timestamp": "x", "extra_field": 1}\n',
        encoding="utf-8",
    )
    append_record(path, _make_record(request_id="after-bad-shape"))
    records = list(read_audit_log(path))
    assert any(r.request_id == "after-bad-shape" for r in records)


def test_read_audit_log_filters_by_since(firm_dir: Path) -> None:
    path = audit_log_path(firm_dir)
    append_record(path, _make_record(ts="2026-09-18T10:00:00.000Z", request_id="old"))
    append_record(path, _make_record(ts="2026-09-19T10:00:00.000Z", request_id="new"))
    since = datetime(2026, 9, 19, 0, 0, 0, tzinfo=UTC)
    records = list(read_audit_log(path, since=since))
    assert [r.request_id for r in records] == ["new"]


def test_read_audit_log_filters_by_until(firm_dir: Path) -> None:
    path = audit_log_path(firm_dir)
    append_record(path, _make_record(ts="2026-09-18T10:00:00.000Z", request_id="old"))
    append_record(path, _make_record(ts="2026-09-19T10:00:00.000Z", request_id="new"))
    until = datetime(2026, 9, 18, 23, 59, 59, tzinfo=UTC)
    records = list(read_audit_log(path, until=until))
    assert [r.request_id for r in records] == ["old"]


def test_read_audit_log_missing_file_is_empty(firm_dir: Path) -> None:
    path = audit_log_path(firm_dir)
    records = list(read_audit_log(path))
    assert records == []


# ---- prune ----


def test_prune_older_than_removes_old_records(firm_dir: Path) -> None:
    path = audit_log_path(firm_dir)
    # An "old" record from 2 years ago, a "recent" one from today.
    old_ts = (datetime.now(tz=UTC) - timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[
        :-4
    ] + "Z"
    recent_ts = utc_now_iso()
    append_record(path, _make_record(ts=old_ts, request_id="old"))
    append_record(path, _make_record(ts=recent_ts, request_id="recent"))
    removed = prune_older_than(path, retention_days=90)
    assert removed == 1
    remaining = list(read_audit_log(path))
    assert [r.request_id for r in remaining] == ["recent"]


def test_prune_older_than_handles_missing_file(firm_dir: Path) -> None:
    path = audit_log_path(firm_dir)
    assert prune_older_than(path, retention_days=90) == 0


def test_prune_older_than_zero_days_keeps_nothing_old(firm_dir: Path) -> None:
    """Edge case: retention_days=0 should remove anything not from this exact instant."""
    path = audit_log_path(firm_dir)
    old_ts = (datetime.now(tz=UTC) - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[
        :-4
    ] + "Z"
    append_record(path, _make_record(ts=old_ts, request_id="old"))
    removed = prune_older_than(path, retention_days=0)
    assert removed == 1
    assert list(read_audit_log(path)) == []


# ---- formatters ----


def test_to_jsonl_emits_one_json_per_line() -> None:
    recs = [_make_record(request_id=f"r-{i}") for i in range(3)]
    body = to_jsonl(iter(recs))
    lines = body.splitlines()
    assert len(lines) == 3
    for line in lines:
        json.loads(line)  # each line parses


def test_to_json_emits_an_array() -> None:
    recs = [_make_record(request_id=f"r-{i}") for i in range(2)]
    body = to_json(iter(recs))
    parsed = json.loads(body)
    assert isinstance(parsed, list)
    assert len(parsed) == 2


def test_to_csv_has_header_and_correct_rows() -> None:
    recs = [_make_record(request_id="csv-1"), _make_record(request_id="csv-2")]
    body = to_csv(iter(recs))
    reader = csv.DictReader(io.StringIO(body))
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["request_id"] == "csv-1"
    assert rows[0]["firm_slug"] == "demo"
    # Header must contain every AuditRecord field name.
    for field_name in AuditRecord.__dataclass_fields__:
        assert field_name in reader.fieldnames  # type: ignore[attr-defined]


def test_to_markdown_table_format() -> None:
    recs = [_make_record(request_id="md-1")]
    body = to_markdown(recs)
    assert body.startswith("|")
    assert "request_id" in body
    assert "md-1" in body
    assert "---" in body  # header separator row


def test_to_markdown_empty_input() -> None:
    body = to_markdown([])
    assert "_no records_" in body


# ---- request_id ----


def test_request_id_now_returns_valid_uuid() -> None:
    """The returned string should look like a UUID."""
    rid = request_id_now()
    # UUIDs are 36 chars including hyphens.
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        rid,
    ), f"not a UUID: {rid!r}"


def test_request_id_now_two_calls_are_distinct() -> None:
    a = request_id_now()
    b = request_id_now()
    assert a != b


def test_utc_now_iso_format() -> None:
    ts = utc_now_iso()
    # Shape: YYYY-MM-DDTHH:MM:SS.fffZ
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", ts), ts
    # And it round-trips back to a datetime within 2 seconds.
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    now = datetime.now(tz=UTC)
    assert abs((now - parsed).total_seconds()) < 2


# ---- privacy policy: never log the question or answer text ----


def test_appended_records_never_contain_question_or_answer_text(firm_dir: Path) -> None:
    """Privacy: the question and answer texts must never appear in the log."""
    path = audit_log_path(firm_dir)
    secret_question = "SECRET_QUESTION_TOKEN_XYZ123"
    secret_answer = "SECRET_ANSWER_TOKEN_XYZ456"
    append_record(
        path,
        _make_record(
            request_id="privacy-1",
            question=secret_question,
            answer=secret_answer,
        ),
    )
    raw = path.read_text(encoding="utf-8")
    assert secret_question not in raw
    assert secret_answer not in raw
    # But the hash of each is present.
    assert hash_text(secret_question) in raw
    assert (
        hash_text(secret_answer) not in raw
    )  # we don't even store the hash of the answer (len only)
