# Changelog

All notable changes to firm-bot are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

(nothing yet — current development happens on `main`)

## [0.1.1] — 2026-09-18

Documentation and asset refresh. No Python package changes; the
wheel and sdist on this release are byte-identical to v0.1.0. Cut as
a new release so the GitHub release index shows the refreshed docs.

### Added
- **`WHITEPAPER.md`** (~5,300 words / 929 lines). Formal technical
  whitepaper for sales calls, partner reviews, conference
  proceedings, formal RFP responses. Covers the compliance gap
  (privilege, GDPR/HIPAA, air-gap, protective orders), STRIDE threat
  model, six-stage architecture, design rationale, benchmarks
  (CUAD/RAGAS/load), honest limitations, roadmap, three appendices.
- **`ARTICLE_DEVTO.md`** (~2,000 words). Full Dev.to article
  replacing the prior outline. Real code from `firm_bot/chunk.py`
  and `firm_bot/answer/prompt.py`. Honest limitations section.
- **`ARTICLE_BLOG.md`** (~2,200 words). Engineering deep-dive for
  Medium / Substack / Hashnode. Four real incident post-mortems
  (OCR rotation, regex cross-doc collisions, Chroma slug validation,
  RFC 2047 EML corner).
- **`TWEETS.md`** (3 threads × 7 tweets = 21 tweets, all ≤280 chars).
  Structure-aware chunker thread, STRIDE threat model thread,
  benchmarks + honest limitations thread.
- **`PRODUCT_HUNT.md`** (~1,300 words). Tagline (54 chars), short
  description (242 chars), long description, maker's first-comment +
  launch-day comment, 4 themes to hunt for in launch-day replies.
- **`INDIE_HACKERS.md`** (~820 words). First-person launch post with
  specific origin story, 4 honest hard parts, 3 feedback questions,
  transparent revenue position, tech stack with reasoning.
- **`MARKETING.md`** updated with a long-form artifacts index at
  the top, an expanded 9-channel list, and a fixed explainer voice
  reference (Alex → Samantha with `[[slnc N]]` prosody pauses).
- **`real-demo-recording.mp4`** (438 KB, 14.7s, 1280×720 H.264).
  Playwright capture of the actual UI: user question, streaming
  answer with `[Article 4.2]` citation marker, 6 retrieved source
  chunks with scores. Replaces the synthetic demo GIF.
- **Three explainer videos with Samantha voice + prosody pauses**
  (`why-firm-bot.mp4`, `what-is-it.mp4`, `magic-sauce.mp4`).
  Replaced the v2 Alex voice with Samantha (US English female) at
  175 wpm with `[[slnc N]]` prosody pauses between sentences. Same
  1920×1080 / 30fps / H.264 slow / crf 18 video quality.

### Changed
- **`scripts/marketing/render_explainers_v3.py`** (new). The
  Samantha-voice + prosody-pauses renderer. Replaces
  `render_explainers_v2.py` (kept for reference).
- **`scripts/marketing/record_real_ui.py`** (new). Real-screen
  recorder using Playwright. Send-button click fix:
  `page.locator("#send-btn").click()` instead of
  `chat_input.press("Enter")` (the textarea's Enter only inserts a
  newline; only the Send button submits the form).

### Distribution
- New GitHub Releases install URL:
  `pip install https://github.com/Mine-FNL/firm-bot/releases/download/v0.1.1/firm_bot-0.1.0-py3-none-any.whl`
- New GitHub Pages PEP 503 simple index (stable, recommended — no signed-URL freshness dependency):
  `pip install --extra-index-url https://mine-fnl.github.io/firm-bot/simple/ firm-bot`
  - Served from the `gh-pages` branch; SHA-256 hashes pinned in the index; pip refuses mismatched downloads.
  - Verified end-to-end: `pip index versions firm-bot --extra-index-url https://mine-fnl.github.io/firm-bot/simple/` returns `0.1.0`; `pip download --no-deps` retrieves the wheel; SHA-256 matches the index entry exactly.
- v0.1.1 GitHub release: https://github.com/Mine-FNL/firm-bot/releases/tag/v0.1.1
- GitHub Pages site: https://mine-fnl.github.io/firm-bot/

## [0.1.0] — 2026-09-17

Initial public release. Multi-tenant local-first RAG chatbot builder
for professional services firms (legal, audit, consultancy) with
citation-required answers.

### Added — product surface
- Multi-tenant storage: per-firm Chroma collection + BM25 pickle,
  isolated at the filesystem level.
- PDF ingestion with Tesseract OCR fallback for scanned pages.
- EML / mbox ingestion; preserves sender, recipients, subject, date,
  message-id for citation.
- DOCX ingestion; preserves heading structure for citation.
- Structure-aware chunker: recognises Article / Section / Exhibit /
  Title Case / ALL-CAPS headings; sections are kept distinct under
  the merge step so two short articles do not collapse.
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

### Added — observability (`firm_bot/observability/`)
- `/metrics` Prometheus text exposition endpoint.
- Per-firm counters, end-to-end latency histogram, per-stage
  latency histogram.
- Structured JSON logs via stdlib `dictConfig`.
- Request-id propagation via `X-Request-ID` header and
  `request.state.request_id`.
- Optional — install via `pip install firm-bot[observability]`.

### Added — security hardening (`firm_bot/security/`)
- Per-IP token-bucket rate limit (10 RPS / 20 burst by default).
- Request body size cap (413 before memory read).
- CORS allow-list (fail-closed default).
- Log-redaction `logging.Filter` for credentials.
- Full STRIDE threat model in `SECURITY.md`.

### Added — evaluation
- **RAGAS-style metrics** (`eval/ragas.py`): four metrics —
  faithfulness, answer_relevancy, context_precision,
  context_recall — computed over the (question, contexts, answer)
  triple without requiring the heavy `ragas` package.
- **Concurrent load benchmark** (`eval/load.py`): fires N concurrent
  queries against the in-process ASGI app and reports p50/p95/p99
  latency, throughput, and error rate.
- **Real benchmark** (`eval/compare.py` + `eval/make_compare_corpus.py`):
  compares structure-aware vs naive chunking on a curated contract
  corpus. Outputs JSON + Markdown tables.
- Runs in CI on push to main via `.github/workflows/bench.yml`.

### Added — retrieval improvements
- **Cross-encoder reranker** (`firm_bot/retrieve/rerank.py`).
  Opt-in via `reranker_model` in `data/config.yaml`. Default model
  `cross-encoder/ms-marco-MiniLM-L-6-v2` (~100 MB). ~30 ms per query.
- **PII redaction** (`firm_bot/redact.py`). Regex-based at ingest
  time, categories: SSN, EIN, email, phone, credit card
  (Luhn-validated), IBAN, IPv4. Configurable per-firm via
  `redact_categories`.
- **Incremental indexing**. Ingest tracks per-file SHA-256 hashes;
  re-running `firm-bot ingest` only re-processes changed files.
  Force-reindex with `POST /v1/firms/{slug}/ingest?force=true`.

### Added — API
- **Structured /query response**. `confidence` ([0, 1] heuristic
  from citation presence, guard verdict, retrieval saturation) and
  `latency_ms` (wall-clock) added to every query response.

### Changed
- `RootConfig` gained `rate_limit_rps`, `rate_limit_burst`,
  `max_upload_bytes`, `cors_allow_origins`, `reranker_model`,
  `rerank_top_k`, `incremental_indexing`.
- `IngestStats` now includes `files_skipped` (incremental indexing).
- Test suite expanded to 129 unit tests + 1 opt-in load smoke (130
  total under `FIRM_BOT_RUN_LOAD_BENCH=1`).
- Coverage 74.47% (CI-enforced floor).

### Known limitations
- No auth (closed deployment only).
- BM25 is rebuilt on every ingest (fine for firms with <100k chunks).
- OCR is capped at 25 pages per file by default
  (`FIRM_BOT_OCR_PAGES` to override).
- No query audit log.
- Judge prompt assumes English-language contracts (the multilingual
  path is the same but the judge may not flag issues in non-English
  sources reliably).
- Prompt injection via corpus content is not defended (open
  problem; mitigation is application-layer).
- Chunker is validated on legal texts only; mixed corpuses
  (emails + contracts) need a hybrid pass.
- Benchmark coverage is the CUAD subset, RAGAS subset, and the
  custom load benchmark — not general legal Q&A, not adversarial
  inputs, not non-English traditions.
