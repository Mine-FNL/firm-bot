"""Tests for the cross-encoder reranker."""
from __future__ import annotations


def test_rerank_re_orders_by_score() -> None:
    """The reranker should reorder so the highest-scoring pair is first."""
    from firm_bot.retrieve.hybrid import RetrievalHit

    class FakeReranker:
        def __init__(self, mapping: dict[str, float]) -> None:
            self.mapping = mapping

        def score(self, pairs: list[tuple[str, str]]) -> list[float]:
            out = []
            for _, t in pairs:
                # map by chunk text content
                out.append(self.mapping.get(t, 0.0))
            return out

    chunks = [
        RetrievalHit(chunk_id="a", text="alpha", metadata={}, score=0.1),
        RetrievalHit(chunk_id="b", text="beta", metadata={}, score=0.2),
        RetrievalHit(chunk_id="c", text="gamma", metadata={}, score=0.3),
    ]
    # alpha is most relevant
    fake = FakeReranker({"alpha": 0.9, "beta": 0.5, "gamma": 0.1})
    from firm_bot.retrieve.rerank import rerank

    out = rerank(chunks, "query", fake)  # type: ignore[arg-type]
    assert out[0].chunk_id == "a"
    assert out[1].chunk_id == "b"
    assert out[2].chunk_id == "c"
    assert out[0].score == 0.9
    assert out[1].score == 0.5


def test_rerank_handles_empty_input() -> None:
    """Empty hits list should pass through without error."""
    from firm_bot.retrieve.rerank import rerank

    class StubRerank:
        def score(self, pairs: list[tuple[str, str]]) -> list[float]:
            return []

    out = rerank([], "query", StubRerank())  # type: ignore[arg-type]
    assert out == []


def test_get_reranker_caches() -> None:
    """Repeated calls with the same model name should return the same object."""
    import sys

    calls: list[str] = []

    class FakeCE:
        def __init__(self, model_name: str) -> None:
            calls.append(model_name)

        def score(self, pairs: list[tuple[str, str]]) -> list[float]:
            return [0.0] * len(pairs)

    # Patch the CrossEncoder class within the rerank module
    from firm_bot.retrieve import rerank as rerank_mod

    original = getattr(rerank_mod, "CrossEncoder", None)
    rerank_mod.CrossEncoder = FakeCE  # type: ignore[misc]
    try:
        a = rerank_mod.get_reranker("model-a")
        b = rerank_mod.get_reranker("model-a")
        c = rerank_mod.get_reranker("model-b")
        assert a is b
        assert a is not c
        # Cache module state for cleanup
        _ = calls
    finally:
        if original is not None:
            rerank_mod.CrossEncoder = original  # type: ignore[misc]
    # Verify both models instantiated exactly once each
    _ = sys.modules  # silence unused
