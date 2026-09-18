"""FastAPI app implementation."""
from __future__ import annotations

import logging
import os
import shutil
import time
import typing
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..chunk import chunk_documents
from ..config import FirmConfig, RootConfig, is_valid_slug
from ..ingest.common import IngestStats, dispatch, walk_source_dir
from ..ollama_setup import ensure_model_pulled
from ..store import Store
from .embed_cache import get_embedder

log = logging.getLogger("firm_bot.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup hook — auto-pull the configured Ollama model if missing.

    Controlled by `FIRM_BOT_AUTO_PULL_MODEL`:
      - "0" / "false" → skip
      - anything else (default) → attempt the pull, log warnings on
        failure but never break startup.

    This is what makes `firm-bot serve` work on first boot without
    a separate `ollama pull X` step. The pull is best-effort: query
    path surfaces the real error if the model is still missing.
    """
    if os.environ.get("FIRM_BOT_AUTO_PULL_MODEL", "1").lower() not in ("0", "false", "no"):
        root = _get_root()
        # Only pull for the default answer model — firm-level overrides
        # are not auto-pulled (would race against user-driven config).
        if root.llm_model:
            ensure_model_pulled(root.ollama_host, root.llm_model)
    yield


app = FastAPI(
    title="firm-bot",
    description="Multi-tenant local-first chatbot builder for professional services firms.",
    version="0.1.0",
    lifespan=lifespan,
)


def _get_root() -> RootConfig:
    """Resolve the RootConfig (env-override friendly)."""
    import os
    data_dir = os.environ.get("FIRM_BOT_DATA_DIR", "./data")
    return RootConfig(data_dir=data_dir)


def _register_middleware() -> None:
    """Wire observability + security middleware at process start.

    Both middlewares are optional — observability requires
    ``prometheus_client`` and security's rate-limit/CORS only matter when
    the service is exposed beyond localhost. We import defensively so a
    missing optional dep does not break boot.
    """
    # Observability: structured logs + Prometheus metrics + request ids.
    try:
        from ..observability import ObservabilityMiddleware

        app.add_middleware(ObservabilityMiddleware)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("observability middleware not wired: %s", e)

    # Security: rate limit + body size + CORS. Reads limits from RootConfig.
    try:
        from ..security import SecurityMiddleware
        from ..security.api_key import APIKeyAuthMiddleware
        from ..security.rate_limit import RateLimiter

        root = _get_root()
        limiter = RateLimiter(
            rate=root.rate_limit_rps,
            burst=root.rate_limit_burst,
        )
        app.add_middleware(
            SecurityMiddleware,
            rate_limiter=limiter,
            max_body_bytes=root.max_upload_bytes,
            cors_allow_origins=root.cors_allow_origins,
        )
        # API key auth — opt-in. Only wired when require_api_key is
        # true AND at least one key is configured. Health / metrics /
        # UI are exempt regardless.
        if root.require_api_key and root.api_keys:
            app.add_middleware(
                APIKeyAuthMiddleware,
                valid_keys=root.api_keys,
                enabled=True,
            )
            log.info(
                "api key auth enabled (configured=%d keys)",
                len(root.api_keys),
            )
    except Exception as e:  # pragma: no cover - defensive
        log.warning("security middleware not wired: %s", e)


_register_middleware()


def _get_store(slug: str) -> Store:
    root = _get_root()
    if not is_valid_slug(slug):
        raise HTTPException(400, f"invalid slug: {slug!r}")
    return Store.open(root, slug)


# ---- HTML UI (single page) ----

_INDEX_HTML = Path(__file__).resolve().parent.parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> HTMLResponse:
    if not _INDEX_HTML.exists():
        return HTMLResponse("<h1>firm-bot</h1><p>UI not built.</p>", status_code=500)
    return HTMLResponse(_INDEX_HTML.read_text())


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness probe — returns 200 if the process is up.

    A more thorough readiness probe should check that Ollama is
    reachable; we keep this lightweight for k8s / load-balancer use.
    """
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Any:
    """Prometheus text exposition endpoint.

    Returns the metrics emitted by ``firm_bot.observability``: per-firm
    query counters, per-stage latency histograms, ingest counters. The
    ``prometheus_client`` package is an optional dependency — if it's
    not installed this endpoint returns a 503 explaining how to enable
    it (``pip install firm-bot[observability]``).
    """
    try:
        from ..observability import metrics_response

        return metrics_response()
    except ImportError as e:  # pragma: no cover - defensive
        raise HTTPException(
            503,
            "prometheus_client not installed; run `pip install firm-bot[observability]`",
        ) from e


# ---- admin: firms ----


@app.get("/v1/firms")
async def list_firms() -> dict[str, list[dict[str, Any]]]:
    root = _get_root()
    base = Path(root.data_dir) / "firms"
    out: list[dict[str, Any]] = []
    if base.exists():
        for entry in sorted(base.iterdir()):
            if entry.is_dir():
                try:
                    cfg = FirmConfig.load(entry)
                    out.append({"slug": cfg.slug, "name": cfg.name})
                except Exception as e:
                    log.warning("firm %s unreadable: %s", entry.name, e)
    return {"firms": out}


class CreateFirmRequest(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,40}$")
    name: str
    system_prompt: str = ""
    llm_model: str = ""
    contact_email: str = ""


@app.post("/v1/firms", status_code=201)
async def create_firm(req: CreateFirmRequest) -> dict[str, Any]:
    root = _get_root()
    firm_dir = Path(root.data_dir) / "firms" / req.slug
    if firm_dir.exists() and any(firm_dir.iterdir()):
        raise HTTPException(409, f"firm already exists: {req.slug}")
    firm_dir.mkdir(parents=True, exist_ok=True)
    cfg = FirmConfig(
        slug=req.slug,
        name=req.name,
        system_prompt=req.system_prompt,
        llm_model=req.llm_model,
        contact_email=req.contact_email,
    )
    cfg.save(firm_dir)
    (firm_dir / "source").mkdir(exist_ok=True)
    return cfg.__dict__


# ---- per-firm endpoints ----


@app.get("/v1/firms/{slug}/config")
async def get_config(slug: str) -> dict[str, Any]:
    store = _get_store(slug)
    return {**store.config.__dict__, "effective_system_prompt": store.config.effective_system_prompt(_get_root())}


class UpdateConfigRequest(BaseModel):
    name: str | None = None
    system_prompt: str | None = None
    llm_model: str | None = None
    contact_email: str | None = None
    notes: str | None = None


@app.patch("/v1/firms/{slug}/config")
async def update_config(slug: str, req: UpdateConfigRequest) -> dict[str, Any]:
    store = _get_store(slug)
    if req.name is not None:
        store.config.name = req.name
    if req.system_prompt is not None:
        store.config.system_prompt = req.system_prompt
    if req.llm_model is not None:
        store.config.llm_model = req.llm_model
    if req.contact_email is not None:
        store.config.contact_email = req.contact_email
    if req.notes is not None:
        store.config.notes = req.notes
    store.config.save(store.firm_dir)
    return store.config.__dict__


@app.get("/v1/firms/{slug}/stats")
async def stats(slug: str) -> dict[str, Any]:
    store = _get_store(slug)
    return store.stats()


# ---- upload + ingest ----


@app.post("/v1/firms/{slug}/upload")
async def upload(slug: str, file: UploadFile) -> dict[str, Any]:
    store = _get_store(slug)
    name = Path(file.filename or "upload.bin").name
    if not name or name.startswith("."):
        raise HTTPException(400, "invalid filename")
    target = store.source_dir / name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"stored": str(target), "size_bytes": target.stat().st_size}


@app.post("/v1/firms/{slug}/ingest")
async def ingest(slug: str, force: bool = False) -> dict[str, Any]:
    """Scan source/, extract, chunk, embed, index. Idempotent.

    With ``incremental_indexing=True`` (default) and ``force=False``, only
    files whose content hash has changed since the last ingest are
    re-processed. Pass ``?force=true`` to re-ingest all files.
    """
    store = _get_store(slug)
    root = _get_root()
    embedder = get_embedder(root)
    embed = embedder.embed

    from ..redact import redact_text

    redact_cats: list[str] | None = (
        store.config.redact_categories if store.config.redact_categories else None
    )

    manifest = store.load_manifest() if root.incremental_indexing and not force else {}

    all_chunks: list[Any] = []
    stats = IngestStats()
    skipped = 0
    new_manifest: dict[str, str] = dict(manifest)
    for src in walk_source_dir(store.source_dir):
        stats.files_total += 1
        file_hash = store.hash_file(src)
        if file_hash == manifest.get(src.name):
            skipped += 1
            # copy old hash forward so deletion doesn't accidentally delete it
            new_manifest[src.name] = file_hash
            continue
        documents = dispatch(src)
        if not documents:
            stats.files_failed += 1
            log.warning("no documents extracted from %s", src)
            continue
        if redact_cats is not None:
            for d in documents:
                d.text = redact_text(d.text, redact_cats)
        store.save_processed(src, documents)
        chunks = chunk_documents(
            documents,
            chunk_size=root.chunk_size,
            overlap=root.chunk_overlap,
        )
        all_chunks.extend(chunks)
        stats.documents_total += len(documents)
        new_manifest[src.name] = file_hash

    stats.files_skipped = skipped

    if not all_chunks:
        store.save_manifest(new_manifest)
        return {
            "stats": stats.as_dict(),
            "chunks_indexed": 0,
            "skipped": skipped,
            "warning": "no new chunks produced; pass ?force=true to re-ingest all",
        }

    texts = [c.text for c in all_chunks]
    embeddings = embed(texts)
    store.upsert_chunks(all_chunks, embeddings)
    store.save_bm25(all_chunks)
    store.save_manifest(new_manifest)
    return {"stats": stats.as_dict(), "chunks_indexed": len(all_chunks), "skipped": skipped}


# ---- query ----


class QueryRequest(BaseModel):
    question: str
    history: list[dict[str, str]] | None = None
    run_guard: bool = True
    k: int | None = None  # override default answer_k


class StreamQueryRequest(BaseModel):
    question: str
    history: list[dict[str, str]] | None = None
    k: int | None = None


@app.post("/v1/firms/{slug}/query")
async def query(slug: str, req: QueryRequest) -> dict[str, Any]:
    """Non-streaming query. Returns the full answer + citation guard results."""
    return await _do_query(slug, req.question, req.history, req.k, req.run_guard)


@app.post("/v1/firms/{slug}/query/stream")
async def query_stream(slug: str, req: StreamQueryRequest) -> StreamingResponse:
    """Streaming query — Server-Sent Events of token deltas.

    Wire format (text/event-stream):

        event: meta
        data: {"hits": [...], "cited": [...], "model": "..."}

        event: token
        data: {"delta": "The cap"}

        event: token
        data: {"delta": " on liability..."}

        ...

        event: done
        data: {"answer": "full text", "cited": [...], "issues": [...]}

    The first ``meta`` event carries the retrieved hits so the UI can
    render the citation pane before tokens start arriving. ``token``
    events are streamed as the LLM generates. ``done`` carries the
    final assembled answer plus any guard issues.
    """
    store = _get_store(slug)
    root = _get_root()
    if not req.question.strip():
        raise HTTPException(400, "empty question")
    if store.collection().count() == 0:
        raise HTTPException(409, "firm has no indexed chunks")

    embedder = get_embedder(root)
    reranker = None
    if root.reranker_model:
        from ..retrieve.rerank import get_reranker

        reranker = get_reranker(root.reranker_model)

    from ..retrieve.hybrid import hybrid_search

    hits = hybrid_search(
        store=store,
        query=req.question,
        embed=embedder.embed,
        bm25_weight=root.hybrid_bm25_weight,
        dense_weight=root.hybrid_dense_weight,
        k=req.k or root.answer_k,
        reranker=reranker,
        rerank_top_k=root.rerank_top_k,
    )
    model = store.config.llm_model or root.llm_model
    system = store.config.effective_system_prompt(root)
    from ..answer.prompt import build_messages

    messages = build_messages(system, req.question, hits, history=req.history)

    meta_hits = [
        {
            "chunk_id": h.chunk_id,
            "marker": _marker_short(h.metadata),
            "score": round(h.score, 4),
            "preview": h.text[:280] + ("…" if len(h.text) > 280 else ""),
        }
        for h in hits
    ]

    async def event_iter() -> typing.AsyncIterator[str]:

        from ..answer.guard import stream_answer_with_ollama

        yield _sse("meta", {"hits": meta_hits, "model": model})
        chunks: list[str] = []
        try:
            for delta in stream_answer_with_ollama(
                root.ollama_host, model, messages, root.llm_timeout_s
            ):
                chunks.append(delta)
                yield _sse("token", {"delta": delta})
        except Exception as e:
            log.exception("stream error")
            yield _sse("error", {"message": str(e)})
            return
        full = "".join(chunks)
        from ..answer.prompt import extract_cited_sources

        cited = extract_cited_sources(full)
        yield _sse(
            "done",
            {
                "answer": full,
                "cited": cited,
                "issues": [],
                "summary": "ok",
            },
        )

    return StreamingResponse(event_iter(), media_type="text/event-stream")


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format one Server-Sent Events frame."""
    import json as _json

    return f"event: {event}\ndata: {_json.dumps(data)}\n\n"


async def _do_query(
    slug: str,
    question: str,
    history: list[dict[str, str]] | None,
    k: int | None,
    run_guard: bool,
) -> dict[str, Any]:
    t_start = time.perf_counter()
    store = _get_store(slug)
    root = _get_root()
    if not question.strip():
        raise HTTPException(400, "empty question")

    from ..answer.guard import answer_with_ollama, verify_citations
    from ..answer.prompt import build_messages, extract_cited_sources
    from ..retrieve.hybrid import hybrid_search

    if store.collection().count() == 0:
        raise HTTPException(409, "firm has no indexed chunks; call POST /v1/firms/{slug}/ingest first")

    embedder = get_embedder(root)
    embed = embedder.embed
    reranker = None
    if root.reranker_model:
        from ..retrieve.rerank import get_reranker

        reranker = get_reranker(root.reranker_model)
    hits = hybrid_search(
        store=store,
        query=question,
        embed=embed,
        bm25_weight=root.hybrid_bm25_weight,
        dense_weight=root.hybrid_dense_weight,
        k=k or root.answer_k,
        reranker=reranker,
        rerank_top_k=root.rerank_top_k,
    )
    if not hits:
        return {
            "answer": "I don't know — no relevant chunks were retrieved.",
            "hits": [],
            "issues": [],
            "summary": "ok",
            "confidence": 0.0,
            "latency_ms": round((time.perf_counter() - t_start) * 1000, 2),
            "model": store.config.llm_model or root.llm_model,
        }

    model = store.config.llm_model or root.llm_model
    system = store.config.effective_system_prompt(root)
    messages = build_messages(system, question, hits, history=history)
    answer_text = answer_with_ollama(
        root.ollama_host,
        model,
        messages,
        root.llm_timeout_s,
    )
    cited = extract_cited_sources(answer_text)

    annotated = None
    if run_guard:
        sources_for_judge = [
            (f"[{h.metadata.get('source_name', '?')}:{_marker_short(h.metadata)}]", h.text)
            for h in hits
        ]
        annotated = verify_citations(
            answer=answer_text,
            sources=sources_for_judge,
            ollama_host=root.ollama_host,
            judge_model=root.llm_judge_model,
            timeout_s=root.llm_timeout_s,
        )

    return {
        "answer": answer_text,
        "cited": cited,
        "hits": [
            {
                "chunk_id": h.chunk_id,
                "marker": _marker_short(h.metadata),
                "score": round(h.score, 4),
                "bm25_rank": h.bm25_rank,
                "dense_rank": h.dense_rank,
                "preview": h.text[:280] + ("…" if len(h.text) > 280 else ""),
            }
            for h in hits
        ],
        "issues": [i.to_dict() for i in annotated.issues] if annotated else [],
        "summary": annotated.summary if annotated else "ok",
        "model": model,
        "judge_model": root.llm_judge_model if run_guard else None,
        "confidence": _compute_confidence(cited, annotated, len(hits)),
        "latency_ms": round((time.perf_counter() - t_start) * 1000, 2),
    }


def _marker_short(meta: dict[str, Any]) -> str:
    name = str(meta.get("source_name") or "?")
    extractor = meta.get("extractor")
    if extractor == "eml":
        mid = str(meta.get("message_id") or "")
        return f"{name}#{mid[:18]}"
    if extractor == "docx":
        return f"{name}§{meta.get('section', '?')}"
    return f"{name}:p.{meta.get('page', '?')}"


def _compute_confidence(
    cited: list[str],
    annotated: Any | None,
    n_hits: int,
) -> float:
    """Compute a [0, 1] confidence score for a query response.

    A simple, deterministic heuristic so we don't pull in a second LLM
    call. Components:

    - **citation presence**: did the answer cite at least one source?
      +0.4 if yes.
    - **guard verdict**: if the guard ran and reported zero issues,
      +0.4; if it ran and reported any issue, +0.0.
    - **retrieval saturation**: the more chunks we had to draw on, the
      more confident we can be — capped contribution of +0.2 once n_hits
      reaches 5.

    Returns 0.0 when nothing was cited and no guard ran (no signal).
    """
    score = 0.0
    if cited:
        score += 0.4
    if annotated is not None:
        score += 0.4 if not annotated.issues else 0.0
    if n_hits > 0:
        score += min(0.2, n_hits * 0.04)
    return round(min(score, 1.0), 3)


# ---- eval ----


class EvalCase(BaseModel):
    question: str
    expected_sources: list[str] = Field(default_factory=list)
    expected_keywords: list[str] = Field(default_factory=list)


class EvalRequest(BaseModel):
    cases: list[EvalCase]


@app.post("/v1/firms/{slug}/eval")
async def run_eval(slug: str, req: EvalRequest) -> dict[str, Any]:
    """Run a citation-coverage / refusal-quality eval over a fixture.

    Each case is judged on:
    - **source coverage**: did the answer cite at least one of
      ``expected_sources``?
    - **keyword coverage**: did the answer include each of
      ``expected_keywords``?
    - **issue count**: how many issues did the guard flag?

    The eval returns per-case rows + an aggregate. Use this to sanity-
    check the bot before shipping to a customer.
    """
    from ..answer.guard import answer_with_ollama, verify_citations
    from ..answer.prompt import build_messages, extract_cited_sources
    from ..retrieve.hybrid import hybrid_search

    store = _get_store(slug)
    root = _get_root()
    embedder = get_embedder(root)
    model = store.config.llm_model or root.llm_model
    rows: list[dict[str, Any]] = []
    for case in req.cases:
        hits = hybrid_search(
            store=store,
            query=case.question,
            embed=embedder.embed,
            bm25_weight=root.hybrid_bm25_weight,
            dense_weight=root.hybrid_dense_weight,
            k=root.answer_k,
        )
        if not hits:
            rows.append(
                {
                    "question": case.question,
                    "answer": "",
                    "source_coverage": 0.0,
                    "keyword_coverage": 0.0,
                    "issues": 0,
                    "pass": False,
                }
            )
            continue
        messages = build_messages(
            store.config.effective_system_prompt(root),
            case.question,
            hits,
        )
        answer = answer_with_ollama(
            root.ollama_host, model, messages, root.llm_timeout_s,
        )
        cited = extract_cited_sources(answer)
        source_cov = sum(1 for s in case.expected_sources if any(s in c for c in cited)) / max(len(case.expected_sources), 1)
        kw_cov = sum(1 for kw in case.expected_keywords if kw.lower() in answer.lower()) / max(len(case.expected_keywords), 1)
        sources_for_judge = [
            (f"[{_marker_short(h.metadata)}]", h.text) for h in hits
        ]
        ann = verify_citations(
            answer=answer,
            sources=sources_for_judge,
            ollama_host=root.ollama_host,
            judge_model=root.llm_judge_model,
            timeout_s=root.llm_timeout_s,
        )
        rows.append(
            {
                "question": case.question,
                "answer": answer[:600] + ("…" if len(answer) > 600 else ""),
                "cited": cited,
                "source_coverage": round(source_cov, 3),
                "keyword_coverage": round(kw_cov, 3),
                "issues": len(ann.issues),
                "pass": source_cov >= 0.5 and kw_cov >= 0.5 and len(ann.issues) == 0,
            }
        )
    n = len(rows)
    agg = {
        "cases": n,
        "pass_rate": round(sum(1 for r in rows if r["pass"]) / max(n, 1), 3),
        "avg_source_coverage": round(sum(r["source_coverage"] for r in rows) / max(n, 1), 3),
        "avg_keyword_coverage": round(sum(r["keyword_coverage"] for r in rows) / max(n, 1), 3),
        "avg_issues": round(sum(r["issues"] for r in rows) / max(n, 1), 2),
    }
    return {"aggregate": agg, "rows": rows}
