"""Tests for the query-vector LRU cache (perf-report finding #6).

Behaviour pinned here:
  - Identical questions return the same cached vector without calling
    the embedder a second time
  - Distinct questions each call the embedder once
  - LRU eviction drops the oldest entry when max_entries is exceeded
  - ``stats()`` reports hit/miss counts and hit_rate
  - Concurrent misses for the same key all return the same vector
  - ``reset_query_cache()`` clears state (test helper)
"""
from __future__ import annotations

import threading

import pytest

from firm_bot.api.embed_cache import (
    QueryVectorCache,
    cached_query_embedding,
    query_cache_stats,
    reset_query_cache,
)


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic embedder that returns a unique vector per text.

    Used to verify cache hits/misses by counting calls.
    """
    return [[float(ord(c) % 7) for c in t] for t in texts]


def test_cache_returns_same_vector_for_same_question() -> None:
    cache = QueryVectorCache(max_entries=8)
    v1 = cache.get_or_compute("what is the cap?", _fake_embed)
    v2 = cache.get_or_compute("what is the cap?", _fake_embed)
    assert v1 == v2
    assert cache.stats()["hits"] == 1
    assert cache.stats()["misses"] == 1


def test_cache_distinct_questions_each_call_embedder() -> None:
    cache = QueryVectorCache(max_entries=8)
    cache.get_or_compute("q1", _fake_embed)
    cache.get_or_compute("q2", _fake_embed)
    cache.get_or_compute("q3", _fake_embed)
    stats = cache.stats()
    assert stats["misses"] == 3
    assert stats["hits"] == 0


def test_cache_evicts_oldest_when_full() -> None:
    cache = QueryVectorCache(max_entries=3)
    cache.get_or_compute("q1", _fake_embed)
    cache.get_or_compute("q2", _fake_embed)
    cache.get_or_compute("q3", _fake_embed)
    # Fourth entry evicts q1
    cache.get_or_compute("q4", _fake_embed)
    assert cache.stats()["size"] == 3
    # q1 should now be a miss again
    cache.get_or_compute("q1", _fake_embed)
    # misses: q1, q2, q3, q4, q1 (the second q1 call is a miss) = 5
    # hits: 0
    stats = cache.stats()
    assert stats["misses"] == 5
    assert stats["hits"] == 0


def test_cache_lru_promotion_on_hit() -> None:
    """Hitting an old entry promotes it so it survives the next eviction."""
    cache = QueryVectorCache(max_entries=3)
    cache.get_or_compute("q1", _fake_embed)
    cache.get_or_compute("q2", _fake_embed)
    cache.get_or_compute("q3", _fake_embed)
    # Touch q1 to promote it
    cache.get_or_compute("q1", _fake_embed)
    # Now q4 should evict q2 (the oldest non-promoted entry)
    cache.get_or_compute("q4", _fake_embed)
    # q1 should still be cached (hit), q2 should be a miss
    cache.get_or_compute("q1", _fake_embed)
    cache.get_or_compute("q2", _fake_embed)
    stats = cache.stats()
    # misses: q1, q2, q3, q4, q2 (second q2 is a miss) = 5
    # hits: q1 (promotion), q1 (re-touch) = 2
    assert stats["misses"] == 5
    assert stats["hits"] == 2


def test_cache_stats_hit_rate() -> None:
    cache = QueryVectorCache(max_entries=8)
    cache.get_or_compute("q1", _fake_embed)  # miss
    cache.get_or_compute("q1", _fake_embed)  # hit
    cache.get_or_compute("q1", _fake_embed)  # hit
    stats = cache.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["hit_rate"] == pytest.approx(0.6667, abs=1e-3)


def test_cache_empty_stats_zero_hit_rate() -> None:
    cache = QueryVectorCache(max_entries=4)
    stats = cache.stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["hit_rate"] == 0.0
    assert stats["size"] == 0


def test_cache_reset_clears_state() -> None:
    cache = QueryVectorCache(max_entries=4)
    cache.get_or_compute("q1", _fake_embed)
    cache.get_or_compute("q1", _fake_embed)
    assert cache.stats()["hits"] == 1
    cache.reset()
    stats = cache.stats()
    assert stats["size"] == 0
    assert stats["hits"] == 0
    assert stats["misses"] == 0


def test_cache_concurrent_misses_return_same_vector() -> None:
    """Two threads racing on the same key both get the right answer.

    Note: both may run ``embed_fn`` (last write wins, identical
    result) — the contract is correctness, not single-flight.
    """
    cache = QueryVectorCache(max_entries=4)
    results: list[list[float]] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            v = cache.get_or_compute("same question", _fake_embed)
            results.append(v)
        except BaseException as e:  # pragma: no cover - defensive
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # All 8 results should be identical (the fake_embed is deterministic)
    assert all(r == results[0] for r in results)


def test_process_wide_cache_module_helpers() -> None:
    """The module-level helpers delegate to the singleton cache."""
    reset_query_cache()
    v1 = cached_query_embedding("hello", _fake_embed)
    v2 = cached_query_embedding("hello", _fake_embed)
    assert v1 == v2
    stats = query_cache_stats()
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1
    reset_query_cache()
    assert query_cache_stats()["size"] == 0
