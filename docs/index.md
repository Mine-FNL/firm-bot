# firm-bot

> Multi-tenant, **local-first** chatbot builder for professional services firms.
> Drop in your firm's emails, PDFs, contracts → get a chat endpoint that
> answers with **citations**, **no data leaves your machine**.

[![CI](https://img.shields.io/badge/CI-macOS%20%2B%20ubuntu-blue)](https://github.com/firm-bot/firm-bot/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

## At a glance

- **Local-first** — Ollama on the firm's hardware. No cloud, no telemetry.
- **Multi-tenant** — one bot per firm, isolated data, isolated indexes.
- **Citation-mandatory** — every claim carries `[file:page]` markers;
  a second LLM-as-judge flags anything ungrounded.
- **Smart chunker** — recognises `Article I`, `Section 4.2`, `EXHIBIT A`,
  and standalone Title-Case headings like "Term" / "Governing Law".
- **Hybrid retrieval** — BM25 + dense via Reciprocal Rank Fusion,
  optional cross-encoder reranker.
- **Open-weight** — any Ollama model, any sentence-transformers
  embedding (or `fastembed` as a faster alternative).
- **Real benchmark** — `eval/compare.py` on 30 contracts / 59 questions
  with measured precision@k and keyword coverage.

## Quickstart

```bash
pip install firm-bot
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5-coder:7b

firm-bot firm create --slug demo --name "Demo LLP"
cp contract.pdf ./data/firms/demo/source/
firm-bot ingest demo
firm-bot query demo "What's the cap on liability?"
```

For the web UI:

```bash
firm-bot serve --port 7860
# open http://127.0.0.1:7860
```

See [Getting started](getting-started.md) for the full setup.

## What this is

firm-bot is a thin Python tool for firms that want a chatbot over their
own documents without sending them to a cloud provider. The core
problem is **grounded answers** — a lawyer can paste the bot's output
into an email because every factual claim carries a citation marker
and a separate LLM check flags anything that doesn't have one.

The architecture is documented in [Architecture](architecture.md).
The HTTP API is in [HTTP API](api.md). Deployment options are in
[Deployment](deployment.md).

## Why this exists

Off-the-shelf chatbot SaaS for legal / audit / consulting fails on three
friction points:

1. **Data is messy.** Contracts span 100+ pages; PDFs are scanned;
   generic chunkers split clauses mid-sentence and produce chunks the
   operator cannot cite.
2. **Citations, not vibes.** A lawyer cannot paste "Yes, indemnity is
   uncapped" into an email without a page number.
3. **Confidentiality is non-negotiable.** Customer emails, contracts,
   and audit findings must NEVER leave the firm's network.

firm-bot is a thin, hackable Python tool that solves all three.

## Where to next

- [Getting started](getting-started.md) — install + first query
- [Architecture](architecture.md) — how it works
- [CLI](cli.md) — every subcommand
- [HTTP API](api.md) — programmatic access
- [Configuration](configuration.md) — tunables
- [Deployment](deployment.md) — Docker, self-host, multi-firm
- [Benchmarks](benchmarks.md) — measured numbers
- [Security](security.md) — threat model and limits

If you want to extend firm-bot, see
[Contributing](contributing.md).
