"""Per-firm storage for firm-bot.

A firm is a slug like ``acme-llp``. Its data lives under
``<root>/firms/<slug>/``:

    firms/<slug>/
        config.yaml         FirmConfig (system prompt, model overrides)
        source/             Operator drops files here (.pdf / .eml / .docx)
        processed/          Per-file extraction results (json) — for debugging
        store/
            chroma/         Chroma persistent vector store
            bm25.pkl        Pickled BM25 index + tokenised corpus
            meta.pkl        Pickled list[Chunk.metadata] in BM25 order

We never share data between firms. Each Chroma collection name is the
firm slug. ``Store`` is the only module that touches the filesystem
directly — the retriever and answer modules go through it.
"""
from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .chunk import Chunk
from .config import FirmConfig, RootConfig
from .ingest.common import Document

log = logging.getLogger("firm_bot.store")


@dataclass
class RetrievalHit:
    chunk_id: str
    text: str
    metadata: dict[str, object]
    score: float                  # RRF score after fusion
    bm25_rank: int = -1           # -1 if not in BM25 top-k
    dense_rank: int = -1          # -1 if not in dense top-k


class Store:
    """One Store per firm. Construct via ``Store.open(root, slug)``."""

    def __init__(
        self,
        root: RootConfig,
        config: FirmConfig,
        firm_dir: Path,
    ) -> None:
        self.root = root
        self.config = config
        self.slug = config.slug
        self.firm_dir = firm_dir
        self.source_dir = firm_dir / "source"
        self.processed_dir = firm_dir / "processed"
        self.store_dir = firm_dir / "store"
        self.chroma_dir = self.store_dir / "chroma"
        self.bm25_path = self.store_dir / "bm25.pkl"
        self.meta_path = self.store_dir / "meta.pkl"
        for d in (self.source_dir, self.processed_dir, self.store_dir, self.chroma_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._chromadb_client = None
        self._chroma_collection = None
        self._bm25 = None
        self._bm25_corpus: list[list[str]] = []
        self._bm25_meta: list[dict[str, object]] = []

    # --- factory ----------------------------------------------------------

    @classmethod
    def open(cls, root: RootConfig, slug: str) -> Store:
        if not root.data_dir:
            raise ValueError("RootConfig.data_dir is not set")
        firm_dir = Path(root.data_dir) / "firms" / slug
        firm_dir.mkdir(parents=True, exist_ok=True)
        cfg = FirmConfig.load(firm_dir)
        cfg.slug = slug
        return cls(root=root, config=cfg, firm_dir=firm_dir)

    # --- chroma -----------------------------------------------------------

    def chroma(self) -> Any:
        """Lazily create the per-firm Chroma persistent client."""
        if self._chromadb_client is None:
            import chromadb
            client: Any = chromadb.PersistentClient(path=str(self.chroma_dir))
            self._chromadb_client = client
        return self._chromadb_client

    def collection(self) -> Any:
        if self._chroma_collection is None:
            self._chroma_collection = self.chroma().get_or_create_collection(
                name=self.slug,
                metadata={"hnsw:space": "cosine"},
            )
        return self._chroma_collection

    # --- bm25 -------------------------------------------------------------

    def bm25(self) -> Any:
        """Lazily load the pickled BM25 index, or return None if empty."""
        if self._bm25 is None and self.bm25_path.exists():
            with self.bm25_path.open("rb") as f:
                payload = pickle.load(f)
            self._bm25 = payload["index"]
            self._bm25_corpus = payload["corpus"]
        return self._bm25

    def bm25_meta(self) -> list[dict[str, object]]:
        if not self._bm25_meta and self.meta_path.exists():
            with self.meta_path.open("rb") as f:
                self._bm25_meta = pickle.load(f)
        return self._bm25_meta

    # --- file-hash manifest for incremental indexing -------------------

    @property
    def manifest_path(self) -> Path:
        return self.store_dir / "indexed_files.json"

    def load_manifest(self) -> dict[str, str]:
        """Return ``{filename: sha256-hex}`` of the last ingest for this firm."""
        if not self.manifest_path.exists():
            return {}
        try:
            data = json.loads(self.manifest_path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save_manifest(self, mapping: dict[str, str]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(mapping, indent=2, sort_keys=True))

    def hash_file(self, path: Path) -> str:
        """SHA-256 hex digest of ``path``."""
        import hashlib

        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # --- ingest helpers ---------------------------------------------------

    def save_processed(self, source_path: Path, documents: list[Document]) -> None:
        """Persist the extracted Documents as JSON for debugging.

        Filename is the source filename + ``.json``. Operator can grep
        through processed/ to sanity-check that extraction worked.
        """
        out = self.processed_dir / (source_path.name + ".json")
        out.write_text(
            json.dumps(
                {
                    "source": str(source_path),
                    "documents": [d.to_dict() for d in documents],
                },
                indent=2,
            )
        )

    def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Upsert a batch of Chunks + their embeddings into Chroma."""
        if not chunks:
            return
        col = self.collection()
        col.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[c.metadata for c in chunks],
        )

    def save_bm25(self, chunks: list[Chunk]) -> None:
        """(Re)build the BM25 index over the current chunk set.

        For v0.1 we rebuild from scratch on every ingest; for firms with
        10k+ chunks we'd switch to incremental updates. Per-firm full
        rebuild keeps the logic simple and correct.
        """
        from rank_bm25 import BM25Okapi

        from .retrieve.bm25 import tokenise

        corpus = [tokenise(c.text) for c in chunks]
        bm25 = BM25Okapi(corpus) if corpus else None
        with self.bm25_path.open("wb") as f:
            pickle.dump(
                {"index": bm25, "corpus": corpus},
                f,
            )
        with self.meta_path.open("wb") as f:
            pickle.dump([c.metadata for c in chunks], f)
        self._bm25 = bm25
        self._bm25_corpus = corpus
        self._bm25_meta = [c.metadata for c in chunks]

    # --- stats ------------------------------------------------------------

    def stats(self) -> dict[str, int | str]:
        col = self.collection() if self.chroma_dir.exists() else None
        bm25_count = len(self._bm25_corpus) if self._bm25_corpus else (
            len(self.bm25_meta()) if self.meta_path.exists() else 0
        )
        chroma_count = col.count() if col is not None else 0
        return {
            "slug": self.slug,
            "name": self.config.name,
            "chroma_chunks": chroma_count,
            "bm25_chunks": bm25_count,
            "source_files": sum(1 for _ in self.source_dir.rglob("*") if _.is_file()),
            "data_dir": str(self.firm_dir),
        }
