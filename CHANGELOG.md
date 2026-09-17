# Changelog

All notable changes to firm-bot are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Observability** (`firm_bot/observability/`). `/metrics` Prometheus
  text exposition endpoint, per-firm counters, end-to-end latency
  histogram, per-stage latency histogram, structured JSON logs via
  stdlib `dictConfig`, request id propagation via `X-Request-ID` header
  and `request.state.request_id`. Optional — install via
  `pip install firm-bot[observability]`.
- **Security hardening** (`firm_bot/security/`). Per-IP token-bucket
  rate limit (10 RPS / 20 burst by default), request body size cap
  (413 before memory read), CORS allow-list (fail-closed default),
  log-redaction `logging.Filter` for credentials, full STRIDE threat
  model in `SECURITY.md`.
- **RAGAS-style quality evaluation** (`eval/ragas.py`). Four
  metrics — faithfulness, answer_relevancy, context_precision,
  context_recall — computed over the (question, contexts, answer)
  triple without requiring the heavy `ragas` package. Aggregated into
  the end-to-end benchmark report when ground-truth is present.
- **Concurrent load benchmark** (`eval/load.py`). Fires N concurrent
  queries against the in-process ASGI app and reports p50/p95/p99
  latency, throughput, and error rate. Runs in CI on push to main via
  `.github/workflows/bench.yml`.
- **Structured /query response**. `confidence` ([0, 1] heuristic from
  citation presence, guard verdict, retrieval saturation) and
  `latency_ms` (wall-clock) added to every query response.

### Changed
- `RootConfig` gained `rate_limit_rps`, `rate_limit_burst`,
  `max_upload_bytes`, `cors_allow_origins`.
- Test suite expanded from 56 → 130 tests (129 unit + 1 opt-in load smoke).
- Coverage 70.81% → 74.47%.

## [0.1.1] — 2026-09-17

## [0.1.1] — 2026-09-17

Post-release improvements that land cleanly on top of v0.1.

### Added
- **Cross-encoder reranker** (`firm_bot/retrieve/rerank.py`). Opt-in via
  `reranker_model` in `data/config.yaml`. Default model
  `cross-encoder/ms-marco-MiniLM-L-6-v2` (~100 MB). ~30 ms per query.
- **PII redaction** (`firm_bot/redact.py`). Regex-based at ingest time,
  categories: SSN, EIN, email, phone, credit card (Luhn-validated),
  IBAN, IPv4. Configurable per-firm via `redact_categories`.
- **Incremental indexing**. Ingest tracks per-file SHA-256 hashes;
  re-running `firm-bot ingest` only re-processes changed files.
  Force-reindex with `POST /v1/firms/{slug}/ingest?force=true`.
- **Real benchmark** (`eval/compare.py` + `eval/make_compare_corpus.py`).
  Compares structure-aware vs naive chunking on a curated 7-doc
  contract corpus (20 questions). Outputs JSON + Markdown tables.
- **Chunker improvement**: standalone Title-Case headings like
  "Term", "Governing Law", "Permitted Disclosures" are now recognised
  as section markers. Closes the gap with naive chunkers on contracts
  that don't prefix sections with "Article" or "Section".

### Changed
- `IngestStats` now includes `files_skipped` (incremental indexing).
- `RootConfig` gained `reranker_model`, `rerank_top_k`,
  `incremental_indexing`.

## [0.1.0] — 2026-09-17

Initial public release. The product surface is complete end-to-end on
synthetic contracts and ready for pilot customers.

### Added
- Multi-tenant storage: per-firm Chroma collection + BM25 pickle,
  isolated at the filesystem level.
- PDF ingestion with Tesseract OCR fallback for scanned pages.
- EML / mbox ingestion; preserves sender, recipients, subject, date,
  message-id for citation.
- DOCX ingestion; preserves heading structure for citation.
- Structure-aware chunker: recognises Article / Section / Exhibit
  / ALL-CAPS headings; sections are kept distinct under the merge
  step so two short articles do not collapse.
- Hybrid retrieval: BM25 + dense via Reciprocal Rank Fusion
  (k_rrf=60), weights configurable.
- Citation-required prompts: every claim must carry a bracketed
  `[file:page]` marker.
- LLM-as-judge citation guard: flags claims without citations or
  that contradict their cited source.
- CLI (`firm-bot firm|ingest|query|eval|serve`) with consistent
  surface.
- FastAPI server with a single-page HTML/JS chat UI showing expanded
  sources and ⚠️ ungrounded-claim warnings.
- Faithfulness eval harness with pass-rate / source coverage /
  keyword coverage / guard-issue aggregates.
- `all-MiniLM-L6-v2` default embedding model (~80 MB).
- Default LLM `qwen2.5-coder:14b`; judge `qwen2.5-coder:7b`; both
  overrideable per-firm.

### Known limitations
- No auth (closed deployment only).
- No cross-encoder reranker (RRF only).
- BM25 is rebuilt on every ingest (fine for firms with <100k chunks).
- OCR is capped at 25 pages per file by default
  (`FIRM_BOT_OCR_PAGES` to override).
- No query audit log.
- Judge prompt assumes English-language contracts (the multilingual
  path is the same but the judge may not flag issues in non-English
  sources reliably).