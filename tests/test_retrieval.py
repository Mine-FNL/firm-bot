"""Tests for the BM25 + dense + RRF hybrid retrieval."""

from __future__ import annotations


def test_bm25_tokenise_lowercases_and_strips_short() -> None:
    from firm_bot.retrieve.bm25 import tokenise

    toks = tokenise("Article I — Limitation of Liability, Q3 2024")
    assert all(t == t.lower() for t in toks)
    assert all(len(t) >= 2 for t in toks)
    # stopword "of" should be dropped
    assert "of" not in toks


def test_bm25_search_returns_top_k_with_positive_score() -> None:
    """Build a tiny BM25 index, query it, assert the right chunk surfaces."""
    from rank_bm25 import BM25Okapi

    from firm_bot.retrieve.bm25 import bm25_search, tokenise

    corpus = [
        tokenise("Limitation of Liability capped at twelve months of fees"),
        tokenise("Indemnification obligations are uncapped for breach of confidentiality"),
        tokenise("Termination requires thirty days written notice"),
    ]
    bm25 = BM25Okapi(corpus)
    meta = [{"chunk_id": f"c{i}", "parent_doc_id": "doc1", "chunk_index": i} for i in range(3)]

    hits = bm25_search(bm25, meta, "liability cap", k=2)
    assert hits, "expected at least one hit"
    top_cid = hits[0][0]
    assert top_cid == "c0", f"expected c0 (liability) on top, got {top_cid}"


def test_hybrid_fusion_prefers_double_signal() -> None:
    """When both BM25 and dense agree, the chunk should rank first."""
    # We test the fusion only — without spinning up a real store or
    # embedder we patch the helpers directly.
    import firm_bot.retrieve.hybrid as hybrid_mod
    from firm_bot.config import RootConfig
    from firm_bot.retrieve.hybrid import RetrievalHit, hybrid_search

    class _StubStore:
        def __init__(self) -> None:
            self.chroma_data = {
                "c_liability": {
                    "text": "liability cap clause",
                    "metadata": {"source_name": "a.pdf", "page": 4},
                },
                "c_nda": {
                    "text": "nda confidentiality",
                    "metadata": {"source_name": "b.pdf", "page": 1},
                },
            }
            self._chroma_collection = self
            self._bm25 = object()
            self._bm25_meta = [
                {"chunk_id": "c_liability", "parent_doc_id": "doc1", "chunk_index": 0},
                {"chunk_id": "c_nda", "parent_doc_id": "doc1", "chunk_index": 1},
            ]

        def bm25(self):
            return self._bm25

        def bm25_meta(self):
            return self._bm25_meta

        def collection(self):
            return self

        def get(self, ids, include=None):
            docs = []
            metas = []
            for cid in ids:
                docs.append(self.chroma_data[cid]["text"])
                metas.append(self.chroma_data[cid]["metadata"])
            return {"ids": list(ids), "documents": docs, "metadatas": metas}

    # patch the inner helpers
    def fake_bm25(bm25, meta, query, store, k):
        # pretend BM25 thinks c_liability is rank 0, c_nda is rank 1
        order = ["c_liability", "c_nda"]
        return [(c, 1.0, i) for i, c in enumerate(order[:k])]

    def fake_dense(store, query, embed, k):
        # dense ALSO thinks c_liability is rank 0
        return [("c_liability", 0.9, 0), ("c_nda", 0.1, 1)][:k]

    def fake_embed(texts):
        return [[0.0] * 4 for _ in texts]

    hybrid_mod._bm25_with_chunks = fake_bm25  # type: ignore[assignment]
    hybrid_mod._dense_with_chunks = fake_dense  # type: ignore[assignment]

    RootConfig(data_dir="./data")  # sanity: import works
    store = _StubStore()
    hits = hybrid_search(
        store=store,
        query="liability cap",
        embed=fake_embed,
        bm25_weight=0.45,
        dense_weight=0.55,
        k=2,
    )
    assert len(hits) == 2
    assert hits[0].chunk_id == "c_liability"
    assert hits[0].bm25_rank == 0
    assert hits[0].dense_rank == 0
    assert hits[0].score > hits[1].score
    # remove the unused-import lint
    _ = RetrievalHit
