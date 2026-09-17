# Configuration

firm-bot has two configuration layers: a **root config** that holds
global settings (LLM host, default models), and a **firm config** that
holds per-tenant overrides (system prompt, model override).

## Root config (`data/config.yaml`)

```yaml
# Where all firm state lives.
data_dir: ./data

# Local Ollama endpoint.
ollama_host: http://127.0.0.1:11434

# Embedding backend + model.
embedding_backend: sentence-transformers    # or "fastembed"
embedding_model: sentence-transformers/all-MiniLM-L6-v2

# LLM models.
llm_model: qwen2.5-coder:14b                # answer model
llm_judge_model: qwen2.5-coder:7b          # guard / eval judge

# Chunking.
chunk_size: 1200
chunk_overlap: 200
min_chunk_size: 120

# Hybrid retrieval weights.
hybrid_bm25_weight: 0.45
hybrid_dense_weight: 0.55

# Retrieval + answer depth.
retrieve_k: 12
answer_k: 6

# Optional cross-encoder reranker (empty disables).
reranker_model: ""
rerank_top_k: 12

# Incremental indexing: skip files whose hash hasn't changed.
incremental_indexing: true

# Max upload size in bytes.
max_upload_bytes: 209715200    # 200 MB

# Log level.
log_level: INFO
```

All settings can be overridden by environment variables (uppercase,
prefix `FIRM_BOT_`):

```bash
FIRM_BOT_LLM_MODEL=qwen2.5-coder:32b firm-bot query demo "..."
FIRM_BOT_OLLAMA_HOST=http://gpu-server:11434 firm-bot serve
```

## Firm config (`data/firms/<slug>/config.yaml`)

```yaml
slug: demo
name: Demo LLP
system_prompt: "You are a legal assistant for Acme LLP. Always..."
llm_model: qwen2.5-coder:32b      # empty → use root default
contact_email: partner@acme.example
notes: "Audit firm, NDA-protected docs"
redact_categories: [ssn, email, phone, credit_card]
extra: {}
```

### PII redaction categories

Per-firm opt-in. Empty list disables redaction. Supported categories:

| Key           | What it redacts                                   |
|---------------|---------------------------------------------------|
| `ssn`         | US SSN `NNN-NN-NNNN` (with validation)            |
| `ein`         | US EIN `NN-NNNNNNNN`                              |
| `email`       | Email addresses                                   |
| `phone`       | US/international phone numbers                    |
| `credit_card` | Card numbers (Luhn-validated)                     |
| `iban`        | IBAN                                              |
| `ipv4`        | IPv4 addresses                                    |

Matches are replaced with stable category tokens (`[SSN-REDACTED]`)
so the operator can still see *that* a number was there without
seeing *which* one. The retriever still finds the chunk; the model
sees `XX-XXX-XXXX` instead of the actual SSN.

## Embedding backend selection

```yaml
embedding_backend: fastembed
embedding_model: BAAI/bge-small-en-v1.5
```

Install the optional extra first:

```bash
pip install firm-bot[embed-fastembed]
```

ONNX runtime, quantised models, ~2-3x faster on CPU than
sentence-transformers. **Re-ingest the firm after switching** —
embeddings from different backends are not interoperable.

## Cross-encoder reranker

```yaml
reranker_model: cross-encoder/ms-marco-MiniLM-L-6-v2
rerank_top_k: 12
```

Re-orders the top RRF hits by a query-aware cross-encoder score. ~30 ms
added per query. Default model is ~100 MB; first load downloads from
HuggingFace.

## Validation

`firm_bot.config.RootConfig.validate()` is called on every load.
Failures raise `firm_bot.errors.ConfigError` with a `user_message`
suitable for displaying to the operator.
