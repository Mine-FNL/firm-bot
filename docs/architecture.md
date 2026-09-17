# Architecture

firm-bot is a thin pipeline:

```
   PDFs /     ┌──────────────────────┐
   EML /      │   Ingestion          │
   DOCX ────▶│  ─ pypdf + OCR       │     ┌──────────────────┐
             │  ─ email parser      │────▶│  Smart Chunker   │
             │  ─ python-docx       │     │  ─ Article § 1.2 │
             └──────────────────────┘     │  ─ sentence bnd  │
                                            └────────┬─────────┘
                                                     │
                          ┌──────────────────────────┴────────────────────┐
                          ▼                                            ▼
                  ┌──────────────┐                              ┌──────────────┐
                  │   BM25       │───────► RRF fusion ◄─────────│   Dense      │
                  │  (lexical)   │        weight 60/30          │  (embeddings)│
                  └──────────────┘                              └──────────────┘
                          │                                            │
                          └────────────────┬───────────────────────────┘
                                           ▼
                                ┌──────────────────┐
                                │   Top-K chunks   │   ← optional cross-encoder reranker
                                │   + citations    │
                                └────────┬─────────┘
                                         ▼
                  ┌────────────────────────────────────────┐
                  │  LLM (qwen2.5-coder:14b local)         │
                  │  — citation-required system prompt     │
                  └────────────────┬───────────────────────┘
                                   ▼
                        ┌────────────────────────┐
                        │   Answer + [file:p.4]  │
                        │   ⚠️ guard (7B judge)  │
                        └────────────────────────┘
```

## Ingestion (`firm_bot/ingest/`)

Per-format extractors convert heterogeneous inputs into a stream of
`Document` objects. For PDFs we emit one `Document` per page so the
retriever can cite the exact page. For email we emit one `Document` per
message. For DOCX we emit one `Document` per section (heading-driven).

Each `Document` carries:

```python
doc.doc_id    # stable content hash + page/message key
doc.text      # extracted text
doc.metadata  # {source_name, page, message_id, ...}
```

## Chunker (`firm_bot/chunk.py`)

The structure-aware chunker recognises:

- `Article I`, `Section 4.2`, `EXHIBIT A`, `SCHEDULE 1` (case-insensitive)
- Numbered headings: `1.`, `1.2`, `12.3.4`
- ALL-CAPS single-line headings
- Title-Case single-line headings: `Term`, `Governing Law`,
  `Permitted Disclosures` (≥ 4 chars, 1-5 words)
- Legal preamble markers: `WHEREAS`, `NOW, THEREFORE`, `RECITALS`

Sections are kept distinct — two short articles do not collapse into
one chunk. Over-long sections are split at sentence boundaries with a
configurable overlap.

## Retrieval (`firm_bot/retrieve/`)

### BM25 (`bm25.py`)

Lexical retrieval over the per-firm chunk corpus. Tokeniser is
domain-aware: lowercased, splits on word boundaries, drops a small
legal-domain stopword list (lucene's "of/the/and" set over-strips
contract headers like "Limitation of Liability").

### Dense (`dense.py`)

Cosine similarity over Chroma HNSW. Default embedding model is
`sentence-transformers/all-MiniLM-L6-v2` (80 MB). `fastembed` is an
opt-in alternative for faster CPU inference.

### Hybrid (`hybrid.py`)

Reciprocal Rank Fusion (Cormack et al., 2009) over BM25 + dense:

    rrf_score(d) = sum_s w_s / (k_rrf + rank_s(d))

Weights come from `RootConfig.hybrid_bm25_weight` and
`hybrid_dense_weight` (default 0.45 / 0.55). `k_rrf` is fixed at 60.

### Cross-encoder reranker (`rerank.py`, opt-in)

When `RootConfig.reranker_model` is set (e.g.
`cross-encoder/ms-marco-MiniLM-L-6-v2`), the top-K RRF hits are
re-ordered by a query-aware cross-encoder score. The cross-encoder
does not introduce new chunks — it only re-orders.

~30 ms added per query at K=6. Worth enabling on larger or messier
corpora; redundant on small clean ones.

## Answer (`firm_bot/answer/`)

### Prompt (`prompt.py`)

The default system prompt enforces the citation contract:

> Answer ONLY using the provided source chunks. Cite every factual claim
> with the bracketed source marker exactly as shown in the context, e.g.
> `[contract.pdf:p.4]`. If the sources do not contain the answer, say so
> plainly — do not guess.

A per-firm override is allowed via `FirmConfig.system_prompt`.

### Guard (`guard.py`)

A second LLM (the "judge") reads the assistant's answer and the cited
sources, then flags:

- `supported` — claim has a citation AND the source supports it
- `unsupported` — claim has a citation but the source doesn't back it,
  OR the claim has no citation at all
- `contradicted` — the cited source says the opposite

The guard is a heuristic advisory. A 7B judge over-flags; treat
its output as signal for human review, not as a fail/pass gate.

## Streaming (`firm_bot/api/app.py`)

`POST /v1/firms/{slug}/query/stream` returns Server-Sent Events of
token deltas as Ollama generates. Wire format:

```
event: meta
data: {"hits": [...], "model": "..."}

event: token
data: {"delta": "The cap"}

event: done
data: {"answer": "full text", "cited": [...], "issues": [...]}
```

Streaming skips the post-hoc guard (it would double latency). For the
audit trail, use the non-streaming `/query` endpoint.

## Storage layout

```
data/
├── config.yaml                  # RootConfig (LLM host, model defaults)
└── firms/<slug>/
    ├── config.yaml              # FirmConfig (system prompt, model override)
    ├── source/                  # operator drops files here
    ├── processed/               # per-file extracted text (debug)
    ├── store/
    │   ├── chroma/              # Chroma persistent client
    │   ├── bm25.pkl             # pickled BM25 index
    │   ├── meta.pkl             # pickled chunk metadata in BM25 order
    │   └── indexed_files.json   # SHA-256 manifest (incremental indexing)
    └── config.yaml.bak          # automatic backup from `firm-bot migrate`
```

Per-firm isolation is structural: each firm has its own Chroma
collection, its own BM25 pickle, its own filesystem root.
