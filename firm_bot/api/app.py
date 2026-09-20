"""FastAPI app implementation."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import typing
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
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
    """Startup hook — auto-pull the configured Ollama model if missing
    and ensure at least one API key is configured.

    Controlled by `FIRM_BOT_AUTO_PULL_MODEL`:
      - "0" / "false" → skip
      - anything else (default) → attempt the pull, log warnings on
        failure but never break startup.

    This is what makes `firm-bot serve` work on first boot without
    a separate `ollama pull X` step. The pull is best-effort: query
    path surfaces the real error if the model is still missing.

    API key bootstrap (v0.2 default-on): when ``require_api_key`` is
    True and ``api_keys`` is empty, generate a fresh key, log it
    once with a ``GENERATED_API_KEY`` banner, and persist to
    ``<data_dir>/config.yaml``. The middleware is wired by
    ``_register_middleware`` (import-time) and reads the resulting
    ``api_keys`` list at request time.
    """
    root = _get_root()
    if (
        os.environ.get("FIRM_BOT_AUTO_PULL_MODEL", "1").lower() not in ("0", "false", "no")
        and root.llm_model
    ):
        # Only pull for the default answer model — firm-level overrides
        # are not auto-pulled (would race against user-driven config).
        ensure_model_pulled(root.ollama_host, root.llm_model)
    # Bootstrap API key BEFORE yielding — the middleware relies on
    # api_keys being populated by the time the first request arrives.
    try:
        root.ensure_api_key()
    except Exception as e:  # pragma: no cover - defensive
        log.warning("api key bootstrap failed: %s", e)
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
            cors_allow_methods=root.cors_allow_methods,
            cors_allow_headers=root.cors_allow_headers,
            cors_max_age=root.cors_max_age,
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


# Per-firm ingest locks. Process-local: each uvicorn worker has its own
# dict, which is fine — concurrent ingests across workers are still
# individually safe (save_processed is per-file atomic, upsert_chunks is
# idempotent on chunk_id). What we prevent here is the intra-process
# race where two parallel requests both walk walk_source_dir, both call
# load_manifest(), both call save_manifest() — the second save loses the
# first's progress for any files the first one had finished.
_INGEST_LOCKS: dict[str, asyncio.Lock] = {}


def _ingest_lock_for(slug: str) -> asyncio.Lock:
    """Return (lazily creating) the per-firm asyncio lock."""
    lock = _INGEST_LOCKS.get(slug)
    if lock is None:
        lock = asyncio.Lock()
        _INGEST_LOCKS[slug] = lock
    return lock


def _safe_get_embedder(root: RootConfig) -> Any:
    """Resolve the embedder, mapping load failures to a structured 503.

    The query / ingest / eval endpoints all call this instead of
    ``get_embedder`` directly. A failure here is environmental —
    weights missing, OOM, backend crashed — and should look like
    ``503 embedder_unavailable`` to the operator, not a 500 with a
    stack trace.
    """
    try:
        return get_embedder(root)
    except Exception as e:
        log.exception("embedder load failed")
        raise HTTPException(
            503,
            f"embedder_unavailable: failed to load embedding model: {e}",
        ) from e


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
    # Hard caps on every operator-controlled string. Defends the
    # endpoint against trivial DoS (10 MB question string → 10 MB
    # embed call) and against typos (zero-length slug → regex still
    # matches but the operator clearly meant something else). The
    # body-size middleware catches bigger bodies before we get here.
    slug: str = Field(
        pattern=r"^[a-z0-9][a-z0-9_-]{1,40}$",
        min_length=2,
        max_length=42,
    )
    name: str = Field(min_length=1, max_length=200)
    system_prompt: str = Field(default="", max_length=20_000)
    llm_model: str = Field(default="", max_length=200)
    contact_email: str = Field(default="", max_length=320)


@app.post("/v1/firms", status_code=201)
async def create_firm(req: CreateFirmRequest) -> dict[str, Any]:
    """Create a new firm.

    Race-condition hardening: two concurrent ``POST /v1/firms`` with
    the same slug would both pass the original ``exists()`` check and
    then both ``mkdir(exist_ok=True)``, with last-writer-wins on the
    config. We now use atomic ``mkdir(exist_ok=False)`` so the second
    request gets a clean ``FileExistsError`` → 409.

    We write a sentinel ``.lock`` file first as a stronger guarantee:
    even if a stale empty directory existed from a half-completed
    earlier create, the sentinel prevents a successful re-create until
    the operator cleans up. (See SECURITY.md "Operational notes".)
    """
    root = _get_root()
    firm_dir = Path(root.data_dir) / "firms" / req.slug

    # Pre-flight check is best-effort only — the authoritative gate
    # is the atomic mkdir below. We keep the pre-flight so a clean
    # "already exists" returns a friendlier 409 message without
    # raising an OSError.
    if firm_dir.exists() and any(firm_dir.iterdir()):
        raise HTTPException(409, f"firm already exists: {req.slug}")

    # Atomic create. ``exist_ok=False`` makes mkdir raise FileExistsError
    # if another request raced us to create the dir. We catch that
    # specifically and translate to 409.
    try:
        firm_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise HTTPException(409, f"firm already exists: {req.slug}") from None

    # Sentinel: a 0-byte ``.lock`` file written first so we can
    # distinguish a freshly-created empty dir from one that was
    # abandoned by a crashed previous create. If the sentinel already
    # exists (because mkdir succeeded but a previous run crashed
    # between mkdir and write), we treat the create as a duplicate.
    sentinel = firm_dir / ".lock"
    try:
        sentinel.touch(exist_ok=False)
    except FileExistsError:
        # mkdir succeeded but sentinel existed — likely a stale
        # half-state. Treat as duplicate; operator can clean up
        # the directory manually if needed.
        raise HTTPException(409, f"firm already exists: {req.slug}") from None

    cfg = FirmConfig(
        slug=req.slug,
        name=req.name,
        system_prompt=req.system_prompt,
        llm_model=req.llm_model,
        contact_email=req.contact_email,
    )
    try:
        cfg.save(firm_dir)
        (firm_dir / "source").mkdir(exist_ok=True)
    except Exception:
        # Roll back the sentinel + dir so a transient failure
        # doesn't leave a phantom firm that looks created but has
        # no config.
        with suppress(OSError):
            sentinel.unlink()
        with suppress(OSError):
            firm_dir.rmdir()
        raise
    return cfg.__dict__


# ---- per-firm endpoints ----


@app.get("/v1/firms/{slug}/config")
async def get_config(slug: str) -> dict[str, Any]:
    store = _get_store(slug)
    return {
        **store.config.__dict__,
        "effective_system_prompt": store.config.effective_system_prompt(_get_root()),
    }


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
    """Upload one file into the firm's source/ dir.

    Hardening:
      - ``Path(filename).name`` strips path components, so
        ``../../etc/passwd`` lands as ``passwd``. Combined with the
        slug regex (alphanum + ``-`` + ``_``) and the ``name != ""``
        + ``not name.startswith('.')`` guards, this blocks every
        path-traversal variant I can think of.
      - 0-byte uploads rejected (accidental-empty-file = silent
        ingest failure later).
      - Existing files are rejected with 409 to avoid silently
        overwriting an operator's manual edit; the API contract is
        "upload = create" — to replace, the operator deletes first.
      - Body size cap (root.max_upload_bytes) is enforced upstream
        by SecurityMiddleware, so we don't need a per-file loop
        guard here.
    """
    store = _get_store(slug)
    name = Path(file.filename or "upload.bin").name
    if not name or name.startswith("."):
        raise HTTPException(400, "invalid filename")
    target = store.source_dir / name
    # Defense in depth: target must resolve under source_dir. This
    # should be impossible because ``Path(name).name`` strips path
    # components, but a future refactor that bypasses ``.name``
    # (e.g. using the raw filename) would silently reintroduce path
    # traversal. The explicit containment check makes the invariant
    # load-bearing on the test, not the implementation.
    try:
        target.resolve().relative_to(store.source_dir.resolve())
    except ValueError as e:
        raise HTTPException(400, "invalid filename") from e
    if target.exists():
        raise HTTPException(409, f"file already exists: {name}")
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    size = target.stat().st_size
    if size == 0:
        # Don't leave a 0-byte stub; remove it and tell the caller.
        with suppress(OSError):
            target.unlink()
        raise HTTPException(400, "empty file rejected")
    return {"stored": str(target), "size_bytes": size}


@app.post("/v1/firms/{slug}/ingest")
async def ingest(slug: str, force: bool = False) -> dict[str, Any]:
    """Scan source/, extract, chunk, embed, index. Idempotent.

    With ``incremental_indexing=True`` (default) and ``force=False``, only
    files whose content hash has changed since the last ingest are
    re-processed. Pass ``?force=true`` to re-ingest all files.

    Concurrency: each firm has a process-local ``asyncio.Lock`` so two
    concurrent ``POST /ingest`` calls for the same slug don't race on
    ``save_manifest`` / ``upsert_chunks``. The second caller gets a
    ``409 ingest_in_progress`` with a hint to retry. Locks are
    per-process — for multi-worker uvicorn each worker ingests in
    parallel against the same on-disk state, which is safe because
    both ``save_processed`` (per-file) and ``upsert_chunks`` (idempotent
    via chunk_id) are individually atomic.
    """
    lock = _ingest_lock_for(slug)
    if lock.locked():
        raise HTTPException(409, f"ingest_in_progress: another ingest for '{slug}' is running")
    async with lock:
        return await _do_ingest(slug, force)


async def _do_ingest(slug: str, force: bool) -> dict[str, Any]:
    """Inner ingest — caller holds the per-firm lock."""
    store = _get_store(slug)
    root = _get_root()
    embedder = _safe_get_embedder(root)
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
    try:
        embeddings = embed(texts)
    except Exception as e:
        # Encode failure (model OOM, backend crashed). 503: the operator
        # needs to free memory / restart. We've already saved partial
        # processed docs and chunks — those are safe to keep, the next
        # ingest will redo them because we don't save_manifest below.
        log.exception("embed failed mid-ingest for slug=%s (%d chunks)", slug, len(texts))
        raise HTTPException(
            503,
            f"embedder_unavailable: failed to encode {len(texts)} chunks: {e}",
        ) from e
    store.upsert_chunks(all_chunks, embeddings)
    store.save_bm25(all_chunks)
    store.save_manifest(new_manifest)
    return {"stats": stats.as_dict(), "chunks_indexed": len(all_chunks), "skipped": skipped}


# ---- query ----


class QueryRequest(BaseModel):
    # Question capped at 4 KB. Real legal/audit questions rarely
    # exceed a paragraph; anything larger is almost certainly an
    # embed-loop DoS attempt and is rejected before we touch the
    # embed model.
    question: str = Field(min_length=1, max_length=4096)
    # History capped at 20 turns (40 messages). Multi-turn sessions
    # longer than this are rare; longer histories should be
    # summarised client-side before re-sending.
    history: list[dict[str, str]] | None = Field(default=None, max_length=40)
    run_guard: bool = True
    k: int | None = Field(default=None, ge=1, le=100)


class StreamQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4096)
    history: list[dict[str, str]] | None = Field(default=None, max_length=40)
    k: int | None = Field(default=None, ge=1, le=100)


class BulkQueryItem(BaseModel):
    """One row in a bulk-query request."""

    question: str = Field(min_length=1, max_length=4096)
    history: list[dict[str, str]] | None = Field(default=None, max_length=40)
    run_guard: bool = True
    k: int | None = Field(default=None, ge=1, le=100)
    # Optional client-supplied id so callers can correlate results
    # without re-parsing the question text. Capped at 64 chars so
    # it fits a UUID without letting arbitrary long strings leak into
    # the audit log.
    id: str | None = Field(default=None, max_length=64)


class BulkQueryRequest(BaseModel):
    """Submit up to N questions in one HTTP round-trip.

    Concurrency is capped at ``max_concurrency`` (default 4) to avoid
    stampeding the Ollama server. The response preserves input order
    and pairs each answer with its ``id`` field if the caller provided
    one.
    """

    items: list[BulkQueryItem]
    # max_concurrency capped at 16 — beyond this the asyncio.gather +
    # semaphore contention starts hurting more than it helps, and the
    # caller can always split into two bulk requests if they need more.
    max_concurrency: int = Field(default=4, ge=1, le=16)


@app.post("/v1/firms/{slug}/query")
async def query(slug: str, req: QueryRequest) -> dict[str, Any]:
    """Non-streaming query. Returns the full answer + citation guard results."""
    return await _do_query(slug, req.question, req.history, req.k, req.run_guard)


@app.post("/v1/firms/{slug}/query/bulk")
async def query_bulk(slug: str, req: BulkQueryRequest) -> dict[str, Any]:
    """Submit a batch of questions and get back a parallel-bounded list of answers.

    Concurrency is capped at ``min(len(items), max_concurrency)`` to
    avoid stampeding the local Ollama server. Items run as separate
    ``asyncio`` tasks; each calls ``_do_query`` so the audit-log +
    injection-scan + stage-timer paths all apply per-item.

    The response shape mirrors the input order:

    .. code-block:: json

        {
          "results": [
            {"id": "...", "ok": true, "response": {...}},
            {"id": "...", "ok": false, "error": "..."}
          ],
          "stats": {"total": N, "succeeded": M, "failed": K, "elapsed_ms": ...}
        }

    Failed items do NOT abort the batch — each item is wrapped in a
    try/except so one malformed question can't kill the whole request.
    """
    import time as _time

    if not req.items:
        return {
            "results": [],
            "stats": {"total": 0, "succeeded": 0, "failed": 0, "elapsed_ms": 0.0},
        }
    if len(req.items) > 100:
        # Hard cap to prevent OOM / accidentally massive requests.
        raise HTTPException(400, f"bulk query limited to 100 items, got {len(req.items)}")
    concurrency = max(1, min(len(req.items), req.max_concurrency))
    sem = asyncio.Semaphore(concurrency)

    t_start = _time.perf_counter()

    async def _run_one(item: BulkQueryItem) -> dict[str, Any]:
        async with sem:
            try:
                resp = await _do_query(slug, item.question, item.history, item.k, item.run_guard)
                return {"id": item.id, "ok": True, "response": resp}
            except HTTPException as e:
                return {"id": item.id, "ok": False, "error": str(e.detail), "status_code": e.status_code}
            except Exception as e:  # pragma: no cover - defensive
                log.warning("bulk query item failed: %s", e)
                return {"id": item.id, "ok": False, "error": f"{type(e).__name__}: {e}"}

    results = await asyncio.gather(*[_run_one(it) for it in req.items])
    succeeded = sum(1 for r in results if r["ok"])
    return {
        "results": results,
        "stats": {
            "total": len(results),
            "succeeded": succeeded,
            "failed": len(results) - succeeded,
            "elapsed_ms": round((_time.perf_counter() - t_start) * 1000, 2),
            "concurrency": concurrency,
        },
    }


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

    embedder = _safe_get_embedder(root)

    # Wrap the embed callable so single-element ``embed([question])``
    # calls — the only ones made on the query path — go through the
    # query-vector LRU cache. Multi-element calls (ingest path) pass
    # through untouched so the batched encode path keeps its own
    # batching behaviour. See firm_bot/api/embed_cache.py for the
    # cache semantics + eviction policy.
    def _embed_with_query_cache(texts: list[str]) -> list[list[float]]:
        if len(texts) == 1:
            from .embed_cache import cached_query_embedding

            cached_vec: list[float] = cached_query_embedding(texts[0], embedder.embed)
            return [cached_vec]
        result: list[list[float]] = embedder.embed(texts)
        return result

    reranker = None
    if root.reranker_model:
        from ..retrieve.rerank import get_reranker

        reranker = get_reranker(root.reranker_model)

    from ..retrieve.hybrid import hybrid_search

    hits = hybrid_search(
        store=store,
        query=req.question,
        embed=_embed_with_query_cache,
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
    from ..answer.injection import scan_hits
    from ..answer.prompt import build_messages, extract_cited_sources
    from ..observability import stage_timer
    from ..retrieve.hybrid import hybrid_search

    if store.collection().count() == 0:
        raise HTTPException(
            409, "firm has no indexed chunks; call POST /v1/firms/{slug}/ingest first"
        )

    embedder = _safe_get_embedder(root)
    embed = embedder.embed
    reranker = None
    if root.reranker_model:
        from ..retrieve.rerank import get_reranker

        reranker = get_reranker(root.reranker_model)

    # ---- retrieve ----
    # ``stage_timer`` records to the Prometheus histogram AND yields
    # elapsed_ms for the audit record below — see the perf-report
    # follow-up that wired this in (previously answer_latency_ms was
    # hard-coded to 0.0 in the audit record).
    with stage_timer("retrieve") as t_retrieve:
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
    retrieve_latency_ms = t_retrieve["elapsed_ms"]

    # ---- prompt-injection pre-pass ----
    # Cheap regex scan over retrieved chunks. The real defence is the
    # instruction-defence suffix in ``prompt.build_messages`` plus the
    # guard LLM; this filter exists to surface suspicious chunks on
    # the response payload and audit log so operators can investigate.
    # Off via FIRM_BOT_INJECTION_FILTER=0 for benchmarking.
    inj_enabled = os.environ.get("FIRM_BOT_INJECTION_FILTER", "1").lower() not in (
        "0",
        "false",
        "no",
    )
    injection_hits = 0
    injection_patterns: list[str] = []
    if inj_enabled:
        with stage_timer("injection_scan") as t_inj:
            injection_hits, injection_patterns = scan_hits(hits)
        injection_scan_latency_ms = t_inj["elapsed_ms"]
    else:
        injection_scan_latency_ms = 0.0

    if not hits:
        return {
            "answer": "I don't know — no relevant chunks were retrieved.",
            "hits": [],
            "issues": [],
            "summary": "ok",
            "confidence": 0.0,
            "latency_ms": round((time.perf_counter() - t_start) * 1000, 2),
            "model": store.config.llm_model or root.llm_model,
            "prompt_injection_suspected": injection_hits,
            "prompt_injection_patterns": injection_patterns,
            "stage_latency_ms": {
                "retrieve": retrieve_latency_ms,
                "injection_scan": injection_scan_latency_ms,
            },
        }

    model = store.config.llm_model or root.llm_model
    system = store.config.effective_system_prompt(root)
    messages = build_messages(system, question, hits, history=history)

    # ---- answer LLM ----
    with stage_timer("answer") as t_answer:
        answer_text = answer_with_ollama(
            root.ollama_host,
            model,
            messages,
            root.llm_timeout_s,
        )
    answer_latency_ms = t_answer["elapsed_ms"]
    cited = extract_cited_sources(answer_text)

    annotated = None
    guard_latency_ms = 0.0
    if run_guard:
        sources_for_judge = [
            (f"[{h.metadata.get('source_name', '?')}:{_marker_short(h.metadata)}]", h.text)
            for h in hits
        ]
        with stage_timer("guard") as t_guard:
            annotated = verify_citations(
                answer=answer_text,
                sources=sources_for_judge,
                ollama_host=root.ollama_host,
                judge_model=root.llm_judge_model,
                timeout_s=root.llm_timeout_s,
            )
        guard_latency_ms = t_guard["elapsed_ms"]

    t_end = time.perf_counter()
    total_latency_ms = round((t_end - t_start) * 1000, 2)
    response: dict[str, Any] = {
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
        "latency_ms": total_latency_ms,
        "prompt_injection_suspected": injection_hits,
        "prompt_injection_patterns": injection_patterns,
        "stage_latency_ms": {
            "retrieve": retrieve_latency_ms,
            "injection_scan": injection_scan_latency_ms,
            "answer": answer_latency_ms,
            "guard": guard_latency_ms,
        },
    }

    # ---- audit log ----
    # Fire-and-forget onto a bounded background queue. The synchronous
    # fsync that ``_audit_record`` performs is off the request path
    # now (perf-report finding #2). The semaphore in
    # ``_schedule_audit`` prevents unbounded task accumulation under
    # bursty load — once the queue is full, we fall back to a
    # synchronous write so we never silently drop audit records.
    _schedule_audit(
        slug=slug,
        question=question,
        answer_text=answer_text,
        cited=cited,
        annotated=annotated,
        hits=hits,
        retrieve_latency_ms=retrieve_latency_ms,
        answer_latency_ms=answer_latency_ms,
        guard_latency_ms=guard_latency_ms,
        injection_scan_latency_ms=injection_scan_latency_ms,
        injection_hits=injection_hits,
        injection_patterns=injection_patterns,
        total_latency_ms=total_latency_ms,
        model=model,
        reranker=root.reranker_model or None,
    )

    return response


def _audit_record(
    slug: str,
    question: str,
    answer_text: str,
    cited: Any,
    annotated: Any,
    hits: Any,
    retrieve_latency_ms: float,
    answer_latency_ms: float,
    guard_latency_ms: float,
    injection_scan_latency_ms: float,
    injection_hits: int,
    injection_patterns: list[str],
    total_latency_ms: float,
    model: str,
    reranker: str | None,
) -> None:
    """Append one audit log entry. Best-effort — failures are logged, never raised.

    Per-stage latencies come from ``stage_timer`` wrappers in
    ``_do_query`` rather than being attributed heuristically — the
    pre-0.2 audit record always wrote ``retrieval_latency_ms = total``
    and ``answer_latency_ms = 0``, which made the log useless for
    diagnosing retrieval vs answer regressions.
    """
    from ..audit_log import (
        AuditRecord,
        append_record,
        hash_text,
        request_id_now,
        utc_now_iso,
    )

    # Best-effort write: a misconfigured data dir, full disk, audit-
    # log permission issue, or even a programming error in this
    # function must NEVER propagate to the request thread — audit
    # is best-effort, the user-facing response must not fail because
    # we can't record it. Every line below is wrapped; only
    # KeyboardInterrupt / SystemExit are deliberately allowed to
    # propagate so the process can shut down cleanly.
    try:
        root = _get_root()
        firm_dir = Path(root.data_dir) / "firms" / slug
        path = firm_dir / root.audit_log_filename

        # The pre-existing schema expects ``retrieval_latency_ms`` to
        # include everything up to the answer LLM (retrieve + injection
        # scan), and ``answer_latency_ms`` to include answer + guard.
        # The injection scan is so cheap (<1 ms) that lumping it into
        # retrieval doesn't distort the numbers in practice, and
        # matches the operational question "how long did retrieval
        # take?".
        retrieval_latency_ms = round(retrieve_latency_ms + injection_scan_latency_ms, 2)
        answer_latency_with_guard_ms = round(answer_latency_ms + guard_latency_ms, 2)

        guard_summary = "skipped"
        guard_issue_count = 0
        if annotated is not None:
            guard_summary = annotated.summary or "ok"
            guard_issue_count = len(getattr(annotated, "issues", []) or [])

        record = AuditRecord(
            timestamp=utc_now_iso(),
            request_id=request_id_now(),
            firm_slug=slug,
            question_hash=hash_text(question),
            question_len_chars=len(question),
            answer_len_chars=len(answer_text),
            citation_count=len(cited) if cited else 0,
            guard_summary=guard_summary,
            guard_issue_count=guard_issue_count,
            confidence=_compute_confidence(cited, annotated, len(hits)),
            model=model,
            retrieval_latency_ms=retrieval_latency_ms,
            answer_latency_ms=answer_latency_with_guard_ms,
            total_latency_ms=total_latency_ms,
            hit_count=len(hits),
            reranker=reranker,
            api_key_hash=None,  # populated by middleware in a future pass
            prompt_injection_hits=injection_hits,
            prompt_injection_patterns=list(injection_patterns),
        )
        append_record(path, record)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("audit log write failed for %s: %s", slug, e)


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


@app.get("/v1/firms/{slug}/audit-log")
async def audit_log(
    slug: str,
    since: str | None = None,
    until: str | None = None,
    fmt: str = "json",
) -> Response:
    """Read the per-firm audit log with optional time-window filtering.

    Query parameters:
      - since: ISO 8601 lower bound (default: 90 days ago)
      - until: ISO 8601 upper bound (default: now)
      - fmt: json (array), jsonl (newline-delimited), csv, or md

    Returns the matching records in the requested format. Records
    never include the question or answer text — only their SHA-256
    hashes and lengths. See `firm_bot/audit_log.py` for the schema.

    For a CSV import into a SIEM, use `fmt=csv`. For an Excel pivot,
    use `fmt=json`.
    """
    from ..audit_log import (
        prune_older_than,
        read_audit_log,
        to_csv,
        to_json,
        to_jsonl,
        to_markdown,
    )

    root = _get_root()
    firm_dir = Path(root.data_dir) / "firms" / slug
    path = firm_dir / root.audit_log_filename

    # Prune old records on read if retention > 0
    if root.audit_retention_days > 0:
        try:
            prune_older_than(path, root.audit_retention_days)
        except Exception as e:  # pragma: no cover
            log.warning("audit log prune failed: %s", e)

    since_dt = (
        datetime.fromisoformat(since)
        if since
        else datetime.now(tz=UTC) - timedelta(days=root.audit_retention_days)
    )
    until_dt = datetime.fromisoformat(until) if until else datetime.now(tz=UTC)
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=UTC)
    if until_dt.tzinfo is None:
        until_dt = until_dt.replace(tzinfo=UTC)

    records = list(read_audit_log(path, since=since_dt, until=until_dt))

    if fmt == "csv":
        body = to_csv(iter(records))
        return Response(content=body, media_type="text/csv")
    if fmt == "md":
        body = to_markdown(records)
        return Response(content=body, media_type="text/markdown")
    if fmt == "jsonl":
        body = to_jsonl(iter(records))
        return Response(content=body, media_type="application/x-ndjson")
    # default: json
    body = to_json(iter(records))
    return Response(content=body, media_type="application/json")


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
    embedder = _safe_get_embedder(root)
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
            root.ollama_host,
            model,
            messages,
            root.llm_timeout_s,
        )
        cited = extract_cited_sources(answer)
        source_cov = sum(1 for s in case.expected_sources if any(s in c for c in cited)) / max(
            len(case.expected_sources), 1
        )
        kw_cov = sum(1 for kw in case.expected_keywords if kw.lower() in answer.lower()) / max(
            len(case.expected_keywords), 1
        )
        sources_for_judge = [(f"[{_marker_short(h.metadata)}]", h.text) for h in hits]
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


# ---- audit log scheduling (off-request-path) -----------------------------
#
# The perf report flagged that ``_audit_record`` does a synchronous
# open + write + flush + fsync + close *after* the response is built,
# so every query paid ~1-10 ms of disk latency on the request path.
# We move it to a bounded background queue via ``asyncio.to_thread``.
#
# Behaviour:
#   - Submit the audit as a background task. The request handler
#     returns immediately and never waits on disk.
#   - Bound in-flight tasks with ``_AUDIT_SEMAPHORE`` so a bursty
#     burst can't accumulate thousands of pending tasks.
#   - If the semaphore is full, fall back to a synchronous write on
#     the calling thread — we never silently drop audit records
#     (silently-dropping them would break the compliance story).
#
# This keeps the audit guarantee (every query logged, in order) while
# removing the disk latency from the hot path.

# 64 in-flight audit writes is plenty for any realistic load (a
# saturated 4-worker uvicorn would need 16+ concurrent queries just
# to fill it). Lower if memory-constrained; raise only if you see
# audit-saturation warnings in logs.
_AUDIT_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(64)


class _AuditBackpressure:
    """Tracks whether the audit queue has been saturated recently.

    Used to emit a single warning per saturation event instead of one
    per dropped record (which would flood logs under bursty load).
    """

    def __init__(self) -> None:
        self.warned_once = False

    def maybe_warn(self, current_depth: int) -> None:
        if not self.warned_once:
            log.warning(
                "audit semaphore saturated — falling back to sync write "
                "(%d in-flight); consider raising worker count or reducing "
                "request concurrency",
                current_depth,
            )
            self.warned_once = True

    def reset(self) -> None:
        # Call after the queue drains if you want the next saturation
        # to warn again. Not called automatically — one warning per
        # process lifetime is the intent.
        self.warned_once = False


_AUDIT_BACKPRESSURE = _AuditBackpressure()


def _schedule_audit(**kwargs: Any) -> None:
    """Submit an audit record to the background queue.

    Falls back to a synchronous write if the in-flight semaphore is
    already saturated — never silently drops records. The fallback
    also runs synchronously when called outside an event loop (e.g.,
    in unit tests).

    Every code path inside this function catches exceptions so that
    an audit failure never propagates to the user-facing response.
    The audit log is best-effort: the request handler already has
    the answer in hand and must not fail because we can't record it.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — fall back to sync. This happens in
            # unit tests and during shutdown.
            _audit_record(**kwargs)
            return

        if _AUDIT_SEMAPHORE.locked():
            _AUDIT_BACKPRESSURE.maybe_warn(_AUDIT_SEMAPHORE._value)
            _audit_record(**kwargs)
            return

        async def _runner() -> None:
            async with _AUDIT_SEMAPHORE:
                await asyncio.to_thread(_audit_record, **kwargs)

        # Fire-and-forget: the task is intentionally untracked. Storing
        # the reference would let us accumulate thousands of pending
        # tasks under bursty load; the semaphore above is the bound.
        loop.create_task(_runner())  # noqa: RUF006
    except Exception as e:  # pragma: no cover - defensive
        # Belt-and-braces: even the queueing path itself must not
        # propagate to the caller. If this fires, the audit record
        # is silently dropped — log so an operator can investigate.
        log.warning("audit scheduling failed for %s: %s", kwargs.get("slug", "?"), e)
