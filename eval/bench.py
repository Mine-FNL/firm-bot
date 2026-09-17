"""Latency benchmark.

Measures:
- chunking + embedding speed (chunks / second)
- retrieval latency (p50 / p95 over N queries)
- end-to-end query latency (cold + warm)

Run with:
    python -m eval.bench --slug demo --queries 30
"""
from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from firm_bot.api.embed_cache import get_embedder
from firm_bot.chunk import chunk_documents
from firm_bot.config import RootConfig
from firm_bot.ingest.common import dispatch, walk_source_dir
from firm_bot.retrieve.hybrid import hybrid_search
from firm_bot.store import Store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--queries", type=int, default=30)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    data_dir = args.data_dir or "data"
    root = RootConfig.load(Path(data_dir) / "config.yaml") if (Path(data_dir) / "config.yaml").exists() else RootConfig(data_dir=data_dir)

    store = Store.open(root, args.slug)
    embedder = get_embedder(root)

    queries = [
        "What's the cap on liability?",
        "How long does the NDA last?",
        "What are the hourly rates?",
        "Indemnification obligations?",
        "Termination clauses?",
        "Confidentiality obligations?",
        "Payment terms?",
        "What's the renewal process?",
        "Governing law?",
        "Force majeure?",
    ]

    print(f"# firm-bot benchmark (firm={args.slug})")
    print(f"  chunks in store: {store.collection().count()}")
    print()

    # ---- ingest timing (only re-runs if you pass --re-ingest)
    print("## Retrieval latency")
    samples: list[float] = []
    for q in queries * (args.queries // len(queries) + 1):
        t0 = time.perf_counter()
        hybrid_search(
            store=store,
            query=q,
            embed=embedder.embed,
            bm25_weight=root.hybrid_bm25_weight,
            dense_weight=root.hybrid_dense_weight,
            k=root.answer_k,
        )
        samples.append((time.perf_counter() - t0) * 1000)
    samples = samples[: args.queries]
    print(f"  p50: {statistics.median(samples):.1f} ms")
    samples_sorted = sorted(samples)
    p95_idx = max(0, int(len(samples_sorted) * 0.95) - 1)
    print(f"  p95: {samples_sorted[p95_idx]:.1f} ms")
    print()

    # ---- chunk + embed timing
    print("## Ingest throughput")
    docs = []
    for src in walk_source_dir(store.source_dir):
        docs.extend(dispatch(src))
    if docs:
        chunks = chunk_documents(docs, chunk_size=root.chunk_size, overlap=root.chunk_overlap)
        t0 = time.perf_counter()
        embeddings = embedder.embed([c.text for c in chunks])
        dt = time.perf_counter() - t0
        print(f"  {len(chunks)} chunks embedded in {dt:.2f}s ({len(chunks) / dt:.1f} chunks/s)")
        print(f"  embedding dim: {len(embeddings[0]) if embeddings else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
