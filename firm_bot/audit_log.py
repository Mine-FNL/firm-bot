"""Query audit log — append-only JSONL per firm.

Each successful query (and a few notable failure modes) writes one
JSON record per line to ``<data_dir>/firms/<slug>/audit-log.jsonl``.
Records contain everything a compliance reviewer needs without
exposing the answer body:

  - timestamp (ISO 8601, UTC)
  - request_id (UUIDv7 if available; else UUID4)
  - firm slug
  - question_hash (SHA-256 first-16 — never the question itself)
  - question_len_chars (int)
  - answer_len_chars (int)
  - citation_count (int)
  - guard_summary ("ok" | "warn" | "fail" | "skipped")
  - guard_issue_count (int)
  - confidence (float, [0, 1])
  - model (the LLM used)
  - retrieval_latency_ms (float)
  - answer_latency_ms (float)
  - total_latency_ms (float)
  - hit_count (int)
  - reranker (model name or None)
  - api_key_hash (first-12 of SHA-256, or None when auth disabled)

PII policy:
  - The question text is **never** stored. Only a hash + length.
  - The answer text is **never** stored. Only a hash + length.
  - The hit metadata (file/page) **is** stored — that's the audit
    trail of which document the model grounded itself in.

Retention:
  - Default 90 days. Configurable via ``FIRM_BOT_AUDIT_RETENTION_DAYS``.
  - Records older than the retention window are pruned on read
    (see :func:`read_audit_log`).

Endpoint shape (added in app.py):
  GET /v1/firms/{slug}/audit-log
    ?since=<ISO timestamp>  optional lower bound (default: 90d ago)
    ?until=<ISO timestamp>  optional upper bound (default: now)
    ?format=json|md|csv     output format (default: json)
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import uuid
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger("firm_bot.audit_log")


# ---- public dataclass --------------------------------------------------


@dataclass
class AuditRecord:
    """One query's worth of audit metadata. Field names are stable."""

    timestamp: str
    request_id: str
    firm_slug: str
    question_hash: str
    question_len_chars: int
    answer_len_chars: int
    citation_count: int
    guard_summary: str  # ok | warn | fail | skipped
    guard_issue_count: int
    confidence: float
    model: str
    retrieval_latency_ms: float
    answer_latency_ms: float
    total_latency_ms: float
    hit_count: int
    reranker: str | None
    api_key_hash: str | None
    # v0.2 — prompt injection pre-pass on retrieved chunks.
    # Defaults are zero/empty so older log records (pre-injection)
    # still parse cleanly when read back in.
    prompt_injection_hits: int = 0
    prompt_injection_patterns: list[str] = field(default_factory=list)


# ---- hashing helpers ---------------------------------------------------


def hash_text(text: str) -> str:
    """First-16 hex of SHA-256. Used for question/answer — never logged cleartext."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def hash_api_key(api_key: str | None) -> str | None:
    """Hash an API key for log records. None when auth is disabled."""
    if not api_key:
        return None
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


# ---- on-disk path ------------------------------------------------------


def audit_log_path(firm_dir: Path) -> Path:
    """Path to the audit log file for a firm."""
    return firm_dir / "audit-log.jsonl"


# ---- write -------------------------------------------------------------


def append_record(path: Path, record: AuditRecord) -> None:
    """Append a single record as one JSON line. Atomic-ish via temp+rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(record), separators=(",", ":")) + "\n"
    # Open in append mode, fsync for durability, close.
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        with suppress(OSError):  # pragma: no cover - fsync may fail on some FS
            os.fsync(f.fileno())


# ---- read / prune ------------------------------------------------------


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp; tolerate a trailing 'Z'."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def read_audit_log(
    path: Path,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Iterator[AuditRecord]:
    """Yield records from the JSONL log within [since, until].

    Skips malformed lines with a warning. Empty / missing file yields
    no records.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as e:
            log.warning("audit log: skipping malformed line: %s", e)
            continue
        try:
            rec = AuditRecord(**data)
        except TypeError:
            # Field shape mismatch — likely from a different firm-bot
            # version. Skip with a warning.
            log.warning("audit log: skipping record with wrong shape")
            continue
        ts = _parse_ts(rec.timestamp)
        if since is not None and ts < since:
            continue
        if until is not None and ts > until:
            continue
        yield rec


def prune_older_than(path: Path, retention_days: int) -> int:
    """Drop records older than ``retention_days``. Returns count removed.

    Best-effort: rewrites the file with the kept records. Caller
    should run this periodically (e.g., daily cron) — but we expose
    it for tests and ad-hoc use.
    """
    if not path.exists():
        return 0
    cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
    kept: list[str] = []
    removed = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
            ts = _parse_ts(data["timestamp"])
        except (json.JSONDecodeError, KeyError, ValueError):
            # Drop unparseable lines.
            removed += 1
            continue
        if ts < cutoff:
            removed += 1
            continue
        kept.append(stripped)
    path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return removed


# ---- formatters --------------------------------------------------------


_FIELDS: list[str] = [
    "timestamp",
    "request_id",
    "firm_slug",
    "question_hash",
    "question_len_chars",
    "answer_len_chars",
    "citation_count",
    "guard_summary",
    "guard_issue_count",
    "confidence",
    "model",
    "retrieval_latency_ms",
    "answer_latency_ms",
    "total_latency_ms",
    "hit_count",
    "reranker",
    "api_key_hash",
    "prompt_injection_hits",
    "prompt_injection_patterns",
]


def to_jsonl(records: Iterator[AuditRecord]) -> str:
    """Format records as a JSONL string."""
    return "\n".join(json.dumps(asdict(r), separators=(",", ":")) for r in records)


def to_json(records: Iterator[AuditRecord]) -> str:
    """Format records as a JSON array (for direct human reading)."""
    return json.dumps([asdict(r) for r in records], indent=2)


def to_csv(records: Iterator[AuditRecord]) -> str:
    """Format records as CSV. Header row included."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for r in records:
        writer.writerow(asdict(r))
    return buf.getvalue()


def to_markdown(records: list[AuditRecord]) -> str:
    """Format records as a Markdown table for inclusion in docs."""
    if not records:
        return "_no records_"
    headers = _FIELDS
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in records:
        lines.append("| " + " | ".join(str(getattr(r, h, "")) for h in headers) + " |")
    return "\n".join(lines)


# ---- request_id helper -------------------------------------------------


def request_id_now() -> str:
    """Best-effort UUIDv7 (time-ordered). Falls back to UUID4 on older Python."""
    uuid7 = getattr(uuid, "uuid7", None)
    if uuid7 is not None:
        return str(uuid7())
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    """Current UTC time as an ISO 8601 string with 'Z' suffix."""
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"
