"""Alternative embedding backends for firm-bot.

The default is sentence-transformers (`all-MiniLM-L6-v2`). For firms
that want a smaller, faster, or domain-specific embedder, we expose:

- **fastembed** (optional dep). Uses ONNX Runtime + quantised models;
  ~2-3x faster on CPU than sentence-transformers with comparable
  accuracy. Install with ``pip install fastembed``.

Select via ``data/config.yaml``::

    embedding_backend: sentence-transformers   # default
    # or
    embedding_backend: fastembed
    embedding_model: BAAI/bge-small-en-v1.5    # any fastembed-supported model

The chunker, retrieval, and downstream code are agnostic — both
backends produce ``list[list[float]]`` of unit-normalised vectors, so
mixing them is safe as long as you set ``embedding_model`` consistently
and re-ingest after switching.
"""
from __future__ import annotations

import logging
from threading import Lock
from typing import Any

log = logging.getLogger("firm_bot.embed_backends")

_lock = Lock()
_cached: dict[tuple[str, str], Any] = {}


class _SentenceTransformerEmbedder:
    """The default backend — ``sentence-transformers``."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        log.info("loading sentence-transformers: %s", model_name)
        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        result: list[list[float]] = vecs.tolist()
        return result


class _FastembedEmbedder:
    """Optional backend — ``fastembed`` (ONNX runtime, CPU-friendly)."""

    def __init__(self, model_name: str) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise RuntimeError(
                "fastembed is not installed. Run "
                "`pip install firm-bot[embed-fastembed]` to enable this backend."
            ) from e

        log.info("loading fastembed: %s", model_name)
        self.model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # fastembed returns a generator of numpy arrays
        return [v.tolist() for v in self.model.embed(texts)]


def get_embedder(backend: str, model_name: str) -> Any:
    """Resolve the embedder for ``(backend, model_name)`` with process-level caching."""
    key = (backend, model_name)
    with _lock:
        if key in _cached:
            return _cached[key]
        if backend == "fastembed":
            emb: Any = _FastembedEmbedder(model_name)
        elif backend == "sentence-transformers":
            emb = _SentenceTransformerEmbedder(model_name)
        else:
            raise ValueError(
                f"unknown embedding backend: {backend!r}. "
                f"Choose 'sentence-transformers' or 'fastembed'."
            )
        _cached[key] = emb
        return emb
