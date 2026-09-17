# Operations

## Day-to-day

```bash
# Add a new document to a firm
cp new-contract.pdf data/firms/acme/source/
firm-bot ingest acme                  # incremental by default

# Add many documents at once and watch for changes
firm-bot watch acme                   # auto re-ingest on filesystem changes

# Run the web UI
firm-bot serve --host 127.0.0.1 --port 7860

# One-off question
firm-bot query acme "What's the indemnity cap?"
```

## Monitoring

firm-bot v0.1 logs structured events to stderr (JSON when
`log_level=INFO`, plain text otherwise). Each event includes:

- timestamp
- log level
- module
- message

Useful events to grep for:

- `firm_bot.ingest.pdf` / `eml` / `docx` — extraction warnings
- `firm_bot.api.app` — request log
- `firm_bot.answer.guard` — judge fallback (parse failed)

For real production observability, scrape stderr into your log
aggregator of choice.

## Common operations

### Reset a firm's index

```bash
rm -rf data/firms/<slug>/store
firm-bot ingest <slug> --force
```

This rebuilds the Chroma collection, the BM25 pickle, and the
indexed-files manifest from scratch.

### Inspect a firm's chunk count

```bash
firm-bot firm stats <slug>
# {"chroma_chunks": 1247, "bm25_chunks": 1247, "source_files": 18}
```

### Switch an LLM mid-flight

```bash
firm-bot firm config <slug> --set-llm-model qwen2.5-coder:32b
```

Subsequent queries use the new model. No re-ingest needed (the
embeddings don't change). The previous model's answer is no longer
cached anywhere; you can switch back the same way.

### Switch the embedding model

```bash
# 1. Edit data/config.yaml: change embedding_model
# 2. Re-ingest (required because embeddings are not interoperable)
rm -rf data/firms/<slug>/store
firm-bot ingest <slug> --force
```

### Migration

When upgrading firm-bot, your existing firm configs may be missing
new fields. Run:

```bash
firm-bot migrate <slug>
```

This adds new fields with sensible defaults, preserves your values,
and backs up the original to `config.yaml.bak`.

## Performance tuning

See [Configuration](configuration.md) for the tunables. Common
adjustments:

- **Hard contracts with long clauses**: increase `chunk_size` to 2000
  so each chunk holds a complete clause
- **Many short clauses**: decrease `chunk_size` to 800
- **Slow queries**: lower `answer_k` to 4, disable `reranker_model`
- **Inconsistent answers**: raise `answer_k` to 8, enable
  `reranker_model: cross-encoder/ms-marco-MiniLM-L-6-v2`

## Troubleshooting

**"firm has no indexed chunks"**: run `firm-bot ingest <slug>` first.

**Empty answer with no citations**: the retrieval returned hits but the
LLM couldn't extract an answer. Check `data/firms/<slug>/processed/`
to see what the extraction produced — scanned PDFs that failed OCR
return empty text.

**Slow first query**: the embedding model + LLM models load on first
use. Subsequent queries are sub-second for retrieval and ~1-15s for
the answer.

**Ollama not reachable**: the server logs `httpx.ConnectError` on the
first failed query. Verify `ollama serve` is running and check
`FIRM_BOT_OLLAMA_HOST` matches.
