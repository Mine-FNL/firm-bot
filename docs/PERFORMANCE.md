# Performance

What to expect from firm-bot on common hardware.

## Latency (single-firm, single question, M4 16 GB)

| Stage                              | Cold   | Warm   |
|------------------------------------|--------|--------|
| Sentence-transformers load         | ~6 s   | n/a    |
| Ollama 14B model load              | ~25 s  | n/a    |
| Hybrid retrieval (k=6)            | ~150ms | ~80ms  |
| LLM answer (14B, 200 tokens)      | ~12 s  | ~7 s   |
| LLM judge (7B, 100 tokens)        | ~5 s   | ~3 s   |
| **End-to-end query**              | **~17s** (cold) | **~10s** (warm) |

End-to-end dominates by the answer generation step. Once models are
loaded the retrieval step is negligible.

## Throughput (ingest)

| Corpus                                  | Chunks | Time   | Throughput     |
|-----------------------------------------|--------|--------|----------------|
| 10 PDFs × 30 pages                      | ~900   | ~40 s  | ~22 chunks/s   |
| 100 PDFs × 30 pages                     | ~9,000 | ~7 min | ~22 chunks/s   |
| 1,000 PDFs × 30 pages                   | ~90,000| ~70min | ~22 chunks/s   |

Throughput is embedding-bound. Switching to a smaller embedding model
or running on a GPU moves the dial.

## Memory

| Component             | RAM (warm)  |
|-----------------------|-------------|
| Sentence-transformers (MiniLM) | ~300 MB |
| Ollama 14B Q4_K_M     | ~9 GB       |
| Ollama 7B Q4_K_M      | ~5 GB       |
| Chroma (per firm, 1k chunks) | ~50 MB |
| BM25 (per firm, 1k chunks)   | ~10 MB |

A 16 GB M4 can comfortably run the answer model + judge model + embeddings
simultaneously. A 32 GB machine gives you headroom for two Ollama models
plus a large browser tab.

## Scale ceilings (per firm)

- **Chunks**: tested up to 90k in benchmarks. Chroma HNSW is O(log n) at
  query time, so retrieval stays sub-200 ms up to ~1 M chunks.
- **Documents**: no hard limit; the bottleneck is ingest wall time.
- **Concurrent users**: v0.1 serves one user at a time per firm
  (FastAPI single worker). For multi-user add `--workers N` to
  `firm-bot serve` (each worker loads its own model into memory).

## Tuning knobs

`data/config.yaml`:

```yaml
hybrid_bm25_weight: 0.45       # raise for keyword-heavy contracts
hybrid_dense_weight: 0.55      # raise for paraphrased / semantic queries
retrieve_k: 12                 # candidates before RRF
answer_k: 6                    # chunks fed to the answer LLM
chunk_size: 1200                # larger = fewer chunks, more context per query
chunk_overlap: 200             # raise to ~10% of chunk_size for long contracts
```

`firm-bot firm config <slug> --set-llm-model <name>` to swap the
answer model for one firm (e.g. a smaller 7B for speed, or a 32B for
harder questions).

## Benchmark script

Run `python -m eval.bench --slug <name> --queries 30` against any
firm you've ingested. Reports p50/p95 retrieval latency and ingest
throughput on the current corpus.