"""Cross-encoder reranker for hybrid retrieval.

Why
---
BM25 + dense + RRF is empirically strong but treats every chunk
independently. A *cross-encoder* reads the (query, chunk) pair together
and outputs a calibrated relevance score — strictly more accurate, at
the cost of an extra forward pass per (query, chunk) pair.

Model
-----
Default: ``cross-encoder/ms-marco-MiniLM-L-6-v2`` (~100 MB, runs at
~5 ms per pair on an M4). 6-layer MiniLM; trained on MS-MARCO. For
legal-domain customers, ``BAAI/bge-reranker-base`` is a better fit if
they have a GPU; the default is fine for CPU.

How it's wired
--------------
``hybrid_search`` runs BM25 + dense RRF as before, then if reranking is
enabled, re-orders the top-K (configurable) hits by their cross-encoder
score. The cross-encoder does NOT add new chunks — it only re-orders
what RRF already returned.

Cost
----
For K=6 and 200-token chunks, ~30 ms added to each query. Negligible
compared to the ~7 s answer-generation step.
"""
from __future__ import annotations

import logging
from threading import Lock as ThreadLock

from .hybrid import RetrievalHit

log = logging.getLogger("firm_bot.retrieve.rerank")

_lock = ThreadLock()
_cached: dict[str, CrossEncoder] = {}


class CrossEncoder:
    """Thin wrapper around sentence-transformers CrossEncoder."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder

        log.info("loading cross-encoder: %s", model_name)
        self.model = CrossEncoder(model_name)

    def score(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Score (query, chunk) pairs. Higher = more relevant."""
        if not pairs:
            return []
        scores = self.model.predict(pairs, convert_to_numpy=True)
        return [float(s) for s in scores]


def get_reranker(model_name: str) -> CrossEncoder:
    with _lock:
        if model_name not in _cached:
            _cached[model_name] = CrossEncoder(model_name)
        return _cached[model_name]


def rerank(
    hits: list[RetrievalHit],
    query: str,
    reranker: CrossEncoder,
) -> list[RetrievalHit]:
    """Re-order ``hits`` by cross-encoder relevance to ``query``.

    Returns a NEW list; does not mutate ``hits``. Cross-encoder scores
    overwrite the RRF ``score`` field so downstream consumers see the
    re-ranked ordering directly.
    """
    if not hits:
        return hits
    pairs = [(query, h.text) for h in hits]
    scores = reranker.score(pairs)
    # In-place sort: largest score first
    ordered = sorted(
        zip(scores, hits, strict=True),
        key=lambda sh: sh[0],
        reverse=True,
    )
    out: list[RetrievalHit] = []
    for new_score, h in ordered:
        # Replace RetrievalHit with a copy carrying the new score
        out.append(
            RetrievalHit(
                chunk_id=h.chunk_id,
                text=h.text,
                metadata=h.metadata,
                score=new_score,
                bm25_rank=h.bm25_rank,
                dense_rank=h.dense_rank,
            )
        )
    return out
