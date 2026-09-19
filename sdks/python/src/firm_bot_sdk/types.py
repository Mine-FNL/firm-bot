"""Response payload dataclasses.

The SDK returns plain dataclasses rather than dicts so callers get
type-checker autocomplete and runtime attribute access. Every shape
here mirrors the corresponding firm-bot HTTP endpoint response. The
SDK only depends on the public HTTP contract; it never imports from
``firm_bot.*`` so it stays usable against any firm-bot >= 0.2.0 server.

Field names use ``snake_case`` to match the wire format (``json``
encoder / decoder). Optional fields default to ``None`` to tolerate
older servers that don't yet emit them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FirmSummary:
    """Summary record returned by ``GET /v1/firms``.

    Only the two fields the server actually emits are modelled. Use
    :meth:`FirmBotClient.get_firm` for the full config.
    """

    slug: str
    name: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FirmSummary:
        return cls(slug=str(data["slug"]), name=str(data["name"]))


@dataclass(frozen=True)
class FirmConfig:
    """Full per-firm configuration.

    The server may add new fields across firm-bot releases; unknown
    keys are captured in :attr:`extra` rather than dropped, so a
    newer SDK talking to an older server (or vice versa) still
    round-trips useful data.
    """

    slug: str
    name: str
    system_prompt: str = ""
    llm_model: str = ""
    contact_email: str = ""
    notes: str = ""
    effective_system_prompt: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FirmConfig:
        known = {
            "slug",
            "name",
            "system_prompt",
            "llm_model",
            "contact_email",
            "notes",
            "effective_system_prompt",
        }
        kwargs: dict[str, Any] = {k: data.get(k) for k in known if k in data}
        if "system_prompt" not in kwargs:
            kwargs["system_prompt"] = ""
        if "llm_model" not in kwargs:
            kwargs["llm_model"] = ""
        if "contact_email" not in kwargs:
            kwargs["contact_email"] = ""
        if "notes" not in kwargs:
            kwargs["notes"] = ""
        return cls(extra={k: v for k, v in data.items() if k not in known}, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Serialise back into a JSON-compatible dict for round-tripping."""
        out: dict[str, Any] = dict(self.extra)
        out.update(
            {
                "slug": self.slug,
                "name": self.name,
                "system_prompt": self.system_prompt,
                "llm_model": self.llm_model,
                "contact_email": self.contact_email,
                "notes": self.notes,
            }
        )
        if self.effective_system_prompt is not None:
            out["effective_system_prompt"] = self.effective_system_prompt
        return out


@dataclass(frozen=True)
class IngestResult:
    """Result of ``POST /v1/firms/{slug}/ingest``.

    Mirrors the ``stats`` sub-dict plus the high-level counters the
    server emits. ``warning`` is set when the ingest completed but
    produced no new chunks (e.g. only unchanged files).
    """

    files_total: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    documents_total: int = 0
    chunks_indexed: int = 0
    skipped: int = 0
    warning: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IngestResult:
        stats = data.get("stats") or {}
        return cls(
            files_total=int(stats.get("files_total", 0)),
            files_failed=int(stats.get("files_failed", 0)),
            files_skipped=int(stats.get("files_skipped", 0)),
            documents_total=int(stats.get("documents_total", 0)),
            chunks_indexed=int(data.get("chunks_indexed", 0)),
            skipped=int(data.get("skipped", 0)),
            warning=data.get("warning"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class UploadResult:
    """Result of ``POST /v1/firms/{slug}/upload``."""

    stored: str
    size_bytes: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UploadResult:
        return cls(stored=str(data["stored"]), size_bytes=int(data["size_bytes"]))


@dataclass(frozen=True)
class QueryHit:
    """One retrieved chunk surfaced in a query response."""

    chunk_id: str
    marker: str
    score: float
    bm25_rank: int | None = None
    dense_rank: int | None = None
    preview: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryHit:
        return cls(
            chunk_id=str(data.get("chunk_id", "")),
            marker=str(data.get("marker", "")),
            score=float(data.get("score", 0.0)),
            bm25_rank=(int(data["bm25_rank"]) if data.get("bm25_rank") is not None else None),
            dense_rank=(int(data["dense_rank"]) if data.get("dense_rank") is not None else None),
            preview=str(data.get("preview", "")),
        )


@dataclass(frozen=True)
class QueryIssue:
    """One guard-flagged issue inside a query response."""

    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryIssue:
        return cls(raw=dict(data))


@dataclass(frozen=True)
class QueryResponse:
    """Top-level response of ``POST /v1/firms/{slug}/query``.

    The new prompt-injection and per-stage-latency fields added in
    firm-bot 0.2 are first-class attributes here — see
    :attr:`prompt_injection_suspected` and :attr:`stage_latency_ms`.
    """

    answer: str
    cited: list[str]
    hits: list[QueryHit]
    issues: list[QueryIssue]
    summary: str
    confidence: float
    latency_ms: float
    model: str
    judge_model: str | None = None
    prompt_injection_suspected: int = 0
    prompt_injection_patterns: list[str] = field(default_factory=list)
    stage_latency_ms: dict[str, float] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryResponse:
        return cls(
            answer=str(data.get("answer", "")),
            cited=[str(s) for s in (data.get("cited") or [])],
            hits=[QueryHit.from_dict(h) for h in (data.get("hits") or [])],
            issues=[QueryIssue.from_dict(i) for i in (data.get("issues") or [])],
            summary=str(data.get("summary", "")),
            confidence=float(data.get("confidence", 0.0)),
            latency_ms=float(data.get("latency_ms", 0.0)),
            model=str(data.get("model", "")),
            judge_model=data.get("judge_model"),
            prompt_injection_suspected=int(data.get("prompt_injection_suspected", 0)),
            prompt_injection_patterns=[
                str(p) for p in (data.get("prompt_injection_patterns") or [])
            ],
            stage_latency_ms={
                str(k): float(v) for k, v in (data.get("stage_latency_ms") or {}).items()
            },
            raw=dict(data),
        )


@dataclass(frozen=True)
class AuditLogEntry:
    """One entry from the per-firm audit log.

    The server emits the full AuditRecord schema, which includes
    prompt-injection fields (firm-bot 0.2+). We capture any unknown
    keys in :attr:`extra` so newer server fields don't get dropped on
    older SDK versions.
    """

    timestamp: str
    request_id: str
    firm_slug: str
    question_hash: str
    question_len_chars: int
    answer_len_chars: int
    citation_count: int
    guard_summary: str
    guard_issue_count: int
    confidence: float
    model: str
    retrieval_latency_ms: float
    answer_latency_ms: float
    total_latency_ms: float
    hit_count: int
    reranker: str | None = None
    api_key_hash: str | None = None
    prompt_injection_hits: int = 0
    prompt_injection_patterns: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditLogEntry:
        known = {
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
        }
        kwargs: dict[str, Any] = {}
        for k in known:
            if k in data:
                kwargs[k] = data[k]
        # Backfill default values for keys the server may omit
        # (e.g. older firm-bot that doesn't emit prompt-injection
        # fields). The AuditRecord dataclass on the server does the
        # same for read-back compatibility.
        kwargs.setdefault("prompt_injection_hits", 0)
        kwargs.setdefault("prompt_injection_patterns", [])
        return cls(extra={k: v for k, v in data.items() if k not in known}, **kwargs)


@dataclass(frozen=True)
class EvalResult:
    """Result of ``POST /v1/firms/{slug}/eval``.

    Wraps the per-case rows plus the aggregate summary the server
    emits. Per-case rows are kept as raw dicts because their schema
    may evolve; the aggregate is the stable contract callers should
    rely on.
    """

    aggregate: dict[str, Any]
    rows: list[dict[str, Any]]
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        return float(self.aggregate.get("pass_rate", 0.0))

    @property
    def cases(self) -> int:
        return int(self.aggregate.get("cases", len(self.rows)))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalResult:
        return cls(
            aggregate=dict(data.get("aggregate") or {}),
            rows=[dict(r) for r in (data.get("rows") or [])],
            raw=dict(data),
        )
