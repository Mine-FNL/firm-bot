"""Lazy-loaded embedding model cache + per-process query-embedding LRU.

Sentence-transformers models are heavy (~80MB+ for MiniLM). Loading them
at import time means every CLI invocation eats a startup cost; loading
them per-request means the first user pays a long wait. We compromise:
load once per process, cache on the module, share across CLI invocations
within a single ``uvicorn`` worker (and across CLI invocations during
the same Python process).

For multi-worker uvicorn deployment, each worker pays the load cost
once at startup. That's fine.

Query-vector cache (perf-report finding #6)
-------------------------------------------
``encode()`` is deterministic for a given model + text. Identical
questions therefore produce identical embeddings, and we can cache the
result to skip the 5-15 ms MPS encode cost on hot paths. CUAD-style
eval sets and demo flows have bounded question vocabularies — cache
hit rates under realistic load are high.

Cache is bounded by ``max_entries`` (default 1024). On overflow we
evict the oldest (insertion order, ``dict.popitem(last=False)``).
The cache is keyed on the SHA-256 of the question text — no two
distinct inputs can collide.
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import Any

log = logging.getLogger("firm_bot.api.embed_cache")

_lock = Lock()
_cached: dict[str, Embedder] = {}


class Embedder:
    def __init__(self, model_name: str) -> None:
        import numpy as np
        from sentence_transformers import SentenceTransformer

        log.info("loading embedding model: %s", model_name)
        self.model = SentenceTransformer(model_name)
        self._np = np

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        result: list[list[float]] = vecs.tolist()
        return result


def get_embedder(root: Any) -> Any:
    """Resolve the configured embedding backend with process-level caching."""
    from ..embed_backends import get_embedder as _resolve

    backend = getattr(root, "embedding_backend", "sentence-transformers")
    model = root.embedding_model
    return _resolve(backend, model)


# ---- query-vector LRU cache ---------------------------------------------


class QueryVectorCache:
    """Process-local LRU cache for query embeddings.

    State (cache dict + hit/miss counters) lives on the instance to
    keep the implementation free of ``global`` statements — that way
    tests can construct a fresh cache without monkey-patching module
    globals. The process-wide instance below is the one used by
    ``_do_query``.

    Thread safety: ``OrderedDict`` mutation is not atomic, so every
    read/write is taken under ``self._lock``. The lock is uncontended
    on the hot path (cache lookups are O(1) and the critical section
    is short).
    """

    def __init__(self, max_entries: int = 1024) -> None:
        self.max_entries = max_entries
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._lock = Lock()

    def get_or_compute(self, question: str, embed_fn: Callable[[list[str]], list[list[float]]]) -> list[float]:
        """Return cached embedding for ``question`` or compute + cache it."""
        key = hashlib.sha256(question.encode("utf-8")).hexdigest()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                self._hits += 1
                return cached
        # Compute OUTSIDE the lock so concurrent misses can overlap
        # the actual encode work. Two concurrent misses for the same
        # key both run encode(); the second write wins, but both
        # return identical vectors.
        vec_list = embed_fn([question])
        vec: list[float] = vec_list[0]
        with self._lock:
            self._cache[key] = vec
            if len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)  # evict oldest
            self._misses += 1
        return vec

    def stats(self) -> dict[str, int | float]:
        """Return cache stats for observability."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = round(self._hits / total, 4) if total else 0.0
            return {
                "size": len(self._cache),
                "max": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
            }

    def reset(self) -> None:
        """Clear the cache. Test helper."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0


# Process-wide singleton used by ``_do_query``. Tests construct their
# own ``QueryVectorCache`` for isolation.
_QUERY_VECTOR_CACHE = QueryVectorCache()


def cached_query_embedding(question: str, embed_fn: Callable[[list[str]], list[list[float]]]) -> list[float]:
    """Module-level wrapper around the process-wide query-vector cache."""
    return _QUERY_VECTOR_CACHE.get_or_compute(question, embed_fn)


def query_cache_stats() -> dict[str, int | float]:
    """Return stats for the process-wide cache."""
    return _QUERY_VECTOR_CACHE.stats()


def reset_query_cache() -> None:
    """Clear the process-wide cache. Test helper."""
    _QUERY_VECTOR_CACHE.reset()

