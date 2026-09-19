"""Hybrid retrieval: BM25 + dense via Reciprocal Rank Fusion.

Why fusion and not a learned reranker:
- RRF is one line of code, no extra model weights, no GPU cost.
- It is empirically strong on legal/business corpora where exact
  keyword matches (clause numbers, party names, "indemnify") carry
  signal that dense retrieval alone can miss.
- For v0.1 we accept the ~5% accuracy ceiling of RRF. A cross-encoder
  reranker is a v0.2 add-on.

Reciprocal Rank Fusion (Cormack et al., 2009):
    rrf_score(d) = sum_s w_s / (k_rrf + rank_s(d))

where ``s`` ranges over retrievers, ``w_s`` is the per-retriever weight,
and ``k_rrf`` (often 60) flattens the contribution of lower ranks. We
default to weights from RootConfig (``hybrid_bm25_weight`` and
``hybrid_dense_weight``) and k_rrf=60.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..store import Store

log = logging.getLogger("firm_bot.retrieve.hybrid")

K_RRF = 60


@dataclass
class RetrievalHit:
    chunk_id: str
    text: str
    metadata: dict[str, object]
    score: float
    bm25_rank: int = -1
    dense_rank: int = -1


def hybrid_search(
    store: Store,
    query: str,
    embed: Callable[[list[str]], list[list[float]]],
    bm25_weight: float,
    dense_weight: float,
    k: int,
    pool_k: int | None = None,
    reranker: Any | None = None,
    rerank_top_k: int | None = None,
) -> list[RetrievalHit]:
    """Run BM25 + dense, fuse via RRF, return top-``k`` hits.

    If ``reranker`` is provided, the top ``rerank_top_k`` (or
    ``retrieve_k`` if unset) RRF hits are re-ordered by the cross-encoder
    score before returning. The cross-encoder does not introduce new
    chunks — it only re-orders.
    """
    pool = pool_k or max(k * 2, 16)

    bm25 = store.bm25()
    meta = store.bm25_meta()
    bm25_hits = _bm25_with_chunks(bm25, meta, query, store, pool)

    dense_hits = _dense_with_chunks(store, query, embed, pool)

    # RRF
    scores: dict[str, float] = {}
    bm25_rank_map: dict[str, int] = {}
    dense_rank_map: dict[str, int] = {}
    text_map: dict[str, str] = {}
    meta_map: dict[str, dict[str, object]] = {}

    for cid, _score, rank in bm25_hits:
        bm25_rank_map[cid] = rank
        scores[cid] = scores.get(cid, 0.0) + bm25_weight / (K_RRF + rank + 1)
    for cid, _score, rank in dense_hits:
        dense_rank_map[cid] = rank
        scores[cid] = scores.get(cid, 0.0) + dense_weight / (K_RRF + rank + 1)

    # Fill in text/metadata from store's source chunks (we kept the
    # chunks around via the bm25 path; for dense-only hits we need to
    # fetch metadata from chroma).
    #
    # One chroma.get call covers both BM25-only and dense-only hits:
    # text_map starts empty, so the condition `cid not in text_map`
    # matches every cid in `scores` after the rank loops populate it.
    # A second chroma.get round-trip with the same condition was
    # previously issued here and was dead code on every query path —
    # it always returned no new data because the first call had
    # already populated text_map for the same id set. Removed 2026-09
    # after benchmark showed the second call cost ~1 ms per query
    # (~15-25 % of retrieval on the demo corpus).
    chroma = store.collection()
    missing = [cid for cid in scores if cid not in text_map]
    if missing:
        got = chroma.get(ids=missing, include=["documents", "metadatas"])
        for cid, doc, md in zip(
            got.get("ids", []),
            got.get("documents", []) or [""] * len(missing),
            got.get("metadatas", []) or [{}] * len(missing),
            strict=False,
        ):
            text_map[cid] = doc or ""
            meta_map[cid] = md or {}

    # Order by fused score
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
    out: list[RetrievalHit] = []
    for cid, score in ordered:
        out.append(
            RetrievalHit(
                chunk_id=cid,
                text=text_map.get(cid, ""),
                metadata=meta_map.get(cid, {}),
                score=float(score),
                bm25_rank=bm25_rank_map.get(cid, -1),
                dense_rank=dense_rank_map.get(cid, -1),
            )
        )

    if reranker is not None and out:
        from .rerank import rerank as _rerank

        n = rerank_top_k or len(out)
        head = out[:n]
        tail = out[n:]
        out = _rerank(head, query, reranker) + tail
    return out


def _bm25_with_chunks(
    bm25: Any, meta: list[dict[str, object]], query: str, store: Store, k: int
) -> list[tuple[str, float, int]]:
    from .bm25 import tokenise

    if bm25 is None or not meta:
        return []
    q_tokens = tokenise(query)
    if not q_tokens:
        return []
    scores = bm25.get_scores(q_tokens)
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    out: list[tuple[str, float, int]] = []
    for rank, idx in enumerate(order[:k]):
        if scores[idx] <= 0:
            break
        cid_obj = meta[idx].get("chunk_id") or _derive_chunk_id(meta[idx], idx)
        cid: str = str(cid_obj)
        out.append((cid, float(scores[idx]), rank))
    return out


def _dense_with_chunks(
    store: Store, query: str, embed: Callable[[list[str]], list[list[float]]], k: int
) -> list[tuple[str, float, int]]:
    from .dense import dense_search

    col = store.collection()
    return dense_search(col, query, embed, k)


def _derive_chunk_id(meta: dict[str, object], idx: int) -> str:
    """Build a synthetic chunk_id from metadata when bm25 didn't store one.

    The bm25 path stores meta *without* chunk_id to save space; the
    chunk_id is the parent_doc_id + ':' + chunk_index, which IS in meta.
    """
    parent = meta.get("parent_doc_id") or "meta"
    i = meta.get("chunk_index", idx)
    return f"{parent}:{i}"
