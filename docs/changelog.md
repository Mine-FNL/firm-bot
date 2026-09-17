# Changelog

All notable changes to firm-bot are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

For the canonical changelog (with full detail), see the
`CHANGELOG.md` in the repo root.

## [Unreleased]

### Planned (v0.2)
- Watchdog-driven auto re-ingest on `source/` changes (already in v0.1.1
  as `firm-bot watch`)
- `fastembed` as an alternative embedding backend (CPU-friendly; already
  in v0.1.2)
- Optional LoRA fine-tuning for high-volume customers
- Per-firm usage telemetry / query audit log
- Multi-user auth (API key)
- Streaming responses (SSE) for live token rendering (already in v0.1.2)
- First-class support for cross-document question answering
- Presidio / GLiNER-based NER layer for PII redaction

## [0.1.3] — Wave 7

Post-release additions that close the loop on benchmarking and
upgradability.

### Added
- **End-to-end faithfulness benchmark** (`eval/eval_e2e.py`). Runs
  the full RAG pipeline — retrieve → answer via Ollama → citation
  guard — and reports keyword coverage, citation coverage, guard
  issues, and headline pass rate. Opt-in via Ollama.
- **Config migration** (`firm-bot migrate <slug>`). Upgrades a
  firm's `config.yaml` from v0.1 to the current schema, preserving
  user-set values. Backed up to `config.yaml.bak`.

## [0.1.2] — Wave 6

- SSE streaming responses, `fastembed` backend, expanded benchmark
  (30 contracts / 59 questions).

## [0.1.1] — Wave 5

- Cross-encoder reranker, PII redaction at ingest, incremental
  indexing, structure-aware chunker improvements.

## [0.1.0] — Initial release

- Multi-tenant local-first chatbot builder with citation-required
  answers. PDF / EML / DOCX ingestion, BM25 + dense hybrid
  retrieval, FastAPI + web UI, CLI, faithfulness eval harness.
