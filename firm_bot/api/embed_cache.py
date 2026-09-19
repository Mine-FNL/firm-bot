"""Lazy-loaded embedding model cache.

Sentence-transformers models are heavy (~80MB+ for MiniLM). Loading them
at import time means every CLI invocation eats a startup cost; loading
them per-request means the first user pays a long wait. We compromise:
load once per process, cache on the module, share across CLI invocations
within a single ``uvicorn`` worker (and across CLI invocations during
the same Python process).

For multi-worker uvicorn deployment, each worker pays the load cost
once at startup. That's fine.
"""

from __future__ import annotations

import logging
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
