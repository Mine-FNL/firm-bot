"""Dense retrieval via Chroma cosine similarity.

Chroma already wraps HNSW + cosine, so this is a thin call: embed the
query once, query the firm's collection, return ranked results.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger("firm_bot.retrieve.dense")


def dense_search(
    collection: Any,
    query: str,
    embed: Callable[[list[str]], list[list[float]]],
    k: int,
) -> list[tuple[str, float, int]]:
    """Run a dense query. Returns ``(chunk_id, distance, rank)`` sorted.

    Chroma's ``query`` returns distances (smaller = better for cosine).
    We convert to similarity = 1 - distance so the fusion step is
    monotonic in "better".
    """
    if collection.count() == 0:
        return []
    [q_vec] = embed([query])
    res = collection.query(
        query_embeddings=[q_vec],
        n_results=min(k, collection.count()),
    )
    ids = (res.get("ids") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    out: list[tuple[str, float, int]] = []
    for rank, (cid, dist) in enumerate(zip(ids, dists, strict=False)):
        if cid is None:
            continue
        sim = 1.0 - float(dist)
        out.append((str(cid), sim, rank))
    return out
