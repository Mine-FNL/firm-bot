"""Real benchmark: firm-bot chunker vs naive chunker.

What this measures:
- Retrieval precision@k — for each question, does the top-k retrieval set
  contain at least one chunk from the expected source file?
- Citation coverage — across all questions, what fraction of expected
  source files were retrieved in the top-k?
- Faithfulness proxy — for each (question, retrieved-chunk, expected-keywords)
  triple, what fraction of expected keywords appear in the retrieved chunk?
- Time per query.

Usage:
    python -m eval.compare --out eval/results.json
    python -m eval.compare --markdown
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from firm_bot.api.embed_cache import Embedder, get_embedder
from firm_bot.ingest.common import Document, dispatch
from firm_bot.retrieve.hybrid import RetrievalHit
from firm_bot.retrieve.rerank import CrossEncoder, rerank

log = logging.getLogger("eval.compare")


# ---- naive chunker -----------------------------------------------------


def naive_chunk(doc: Document, chunk_size: int = 1200, overlap: int = 200) -> list[Document]:
    """A sliding-window chunker that ignores document structure.

    This is the baseline. It splits by character count without recognising
    headings or sections — the failure case our structure-aware chunker
    was designed to fix.
    """
    out: list[Document] = []
    text = doc.text
    cursor = 0
    while cursor < len(text):
        end = min(cursor + chunk_size, len(text))
        chunk_text = text[cursor:end]
        out.append(
            Document(
                doc_id=f"{doc.doc_id}:naive-{cursor}",
                text=chunk_text,
                metadata={**doc.metadata, "chunker": "naive", "char_offset": cursor},
            )
        )
        if end >= len(text):
            break
        cursor = end - overlap
    return out


# ---- benchmark harness -------------------------------------------------


@dataclass
class BenchCase:
    question: str
    expected_source: str          # partial filename match
    expected_keywords: list[str] = field(default_factory=list)


@dataclass
class BenchRow:
    question: str
    chunker: str
    expected_source: str
    precision_at_k: float          # 1.0 if top-k hits the expected source
    keyword_coverage: float       # fraction of expected keywords in top-1
    retrieval_ms: float
    top_hit_id: str
    top_hit_source: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchReport:
    cases: list[BenchRow]
    p50_retrieval_ms: dict[str, float]
    p95_retrieval_ms: dict[str, float]
    mean_precision_at_k: dict[str, float]
    mean_keyword_coverage: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "cases": [asdict(r) for r in self.cases],
            "p50_retrieval_ms": self.p50_retrieval_ms,
            "p95_retrieval_ms": self.p95_retrieval_ms,
            "mean_precision_at_k": self.mean_precision_at_k,
            "mean_keyword_coverage": self.mean_keyword_coverage,
        }


def _aggregate(rows: list[BenchRow]) -> BenchReport:
    by_chunker: dict[str, list[BenchRow]] = {}
    for r in rows:
        by_chunker.setdefault(r.chunker, []).append(r)
    p50: dict[str, float] = {}
    p95: dict[str, float] = {}
    mpk: dict[str, float] = {}
    mkc: dict[str, float] = {}
    for chunker, rs in by_chunker.items():
        rs_sorted = sorted(rs, key=lambda r: r.retrieval_ms)
        p50[chunker] = statistics.median([r.retrieval_ms for r in rs])
        idx = max(0, int(len(rs_sorted) * 0.95) - 1)
        p95[chunker] = rs_sorted[idx].retrieval_ms
        mpk[chunker] = statistics.mean([r.precision_at_k for r in rs])
        mkc[chunker] = statistics.mean([r.keyword_coverage for r in rs])
    return BenchReport(
        cases=rows,
        p50_retrieval_ms=p50,
        p95_retrieval_ms=p95,
        mean_precision_at_k=mpk,
        mean_keyword_coverage=mkc,
    )


# ---- main benchmark loop ----------------------------------------------


def run_benchmark(
    fixture_path: Path,
    corpus_dir: Path,
    embedder: Embedder,
    k: int = 6,
) -> BenchReport:
    fixture = json.loads(fixture_path.read_text())
    cases = [BenchCase(**c) for c in fixture["cases"]]
    sources = sorted(corpus_dir.rglob("*.pdf")) + sorted(corpus_dir.rglob("*.docx"))

    # extract once
    all_docs: list[Document] = []
    for src in sources:
        all_docs.extend(dispatch(src))
    log.info("ingested %d documents from %d files", len(all_docs), len(sources))

    # build two chunk corpora: firm_bot (smart) vs naive (sliding window)
    from firm_bot.chunk import chunk_documents

    firm_chunks = chunk_documents(all_docs, chunk_size=1200, overlap=200)
    naive_chunks: list[Document] = []
    for d in all_docs:
        naive_chunks.extend(naive_chunk(d, chunk_size=1200, overlap=200))
    log.info("firm-bot: %d chunks, naive: %d chunks", len(firm_chunks), len(naive_chunks))

    # build an in-memory retrieval index for each chunker
    def _index(chunks: list[Any]) -> tuple[Any, dict[str, Any], list[str]]:
        from rank_bm25 import BM25Okapi

        from firm_bot.retrieve.bm25 import tokenise

        corpus = [tokenise(c.text) for c in chunks]
        bm25: Any = BM25Okapi(corpus)
        ids: list[str] = []
        for i, c in enumerate(chunks):
            cid = getattr(c, "doc_id", None) or getattr(c, "chunk_id", None) or f"chunk-{i}"
            ids.append(str(cid))
        chunk_by_id: dict[str, Any] = {ids[i]: c for i, c in enumerate(chunks)}
        return bm25, chunk_by_id, ids

    firm_bm25, firm_idx, firm_ids = _index(firm_chunks)
    naive_bm25, naive_idx, naive_ids = _index(naive_chunks)

    # embed each chunker
    firm_vecs = embedder.embed([c.text for c in firm_chunks])
    naive_vecs = embedder.embed([c.text for c in naive_chunks])

    rows: list[BenchRow] = []

    def _search(
        chunker: str,
        bm25: Any,
        chunk_idx: dict[str, Document],
        ids: list[str],
        vecs: list[list[float]],
        q: str,
    ) -> tuple[list[RetrievalHit], float]:
        import numpy as np

        from firm_bot.retrieve.bm25 import tokenise

        t0 = time.perf_counter()
        q_tokens = tokenise(q)
        scores = bm25.get_scores(q_tokens)
        q_vec = np.array(embedder.embed([q])[0])
        c_arr = np.array(vecs)
        q_norm = np.linalg.norm(q_vec)
        c_norms = np.linalg.norm(c_arr, axis=1)
        sim = (c_arr @ q_vec) / np.where(c_norms == 0, 1, c_norms) / (q_norm or 1.0)
        bm25_order = np.argsort(-scores)
        dense_order = np.argsort(-sim)
        bm25_rank = {int(idx): r for r, idx in enumerate(bm25_order)}
        dense_rank = {int(idx): r for r, idx in enumerate(dense_order)}
        K = 60
        fused: dict[int, float] = {}
        for idx in range(len(bm25_order)):
            fused[idx] = fused.get(idx, 0.0) + 0.45 / (K + bm25_rank[idx])
        for idx in range(len(dense_order)):
            fused[idx] = fused.get(idx, 0.0) + 0.55 / (K + dense_rank[idx])
        top = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        hits: list[RetrievalHit] = []
        for top_idx, top_score in top:
            top_chunk = chunk_idx[ids[top_idx]]
            hits.append(
                RetrievalHit(
                    chunk_id=ids[top_idx],
                    text=top_chunk.text,
                    metadata=top_chunk.metadata,
                    score=float(top_score),
                    bm25_rank=bm25_rank.get(top_idx, -1),
                    dense_rank=dense_rank.get(top_idx, -1),
                )
            )
        dt_ms = (time.perf_counter() - t0) * 1000
        return hits, dt_ms

    for case in cases:
        for chunker_name, bm25, idx, ids, vecs in [
            ("firm_bot", firm_bm25, firm_idx, firm_ids, firm_vecs),
            ("naive", naive_bm25, naive_idx, naive_ids, naive_vecs),
        ]:
            hits, ms = _search(chunker_name, bm25, idx, ids, vecs, case.question)
            top_hit = hits[0] if hits else None
            source_match = any(
                case.expected_source.lower() in str(h.metadata.get("source_name", "")).lower()
                for h in hits
            )
            if case.expected_keywords and hits:
                kw_cov = max(
                    sum(1 for kw in case.expected_keywords if kw.lower() in h.text.lower())
                    / len(case.expected_keywords)
                    for h in hits
                )
            else:
                kw_cov = 1.0
            rows.append(
                BenchRow(
                    question=case.question,
                    chunker=chunker_name,
                    expected_source=case.expected_source,
                    precision_at_k=1.0 if source_match else 0.0,
                    keyword_coverage=kw_cov,
                    retrieval_ms=ms,
                    top_hit_id=top_hit.chunk_id if top_hit else "",
                    top_hit_source=str(top_hit.metadata.get("source_name", "?")) if top_hit else "?",
                )
            )

    # 3rd column: firm_bot + cross-encoder reranker. Opt-in via env so
    # the benchmark doesn't pull the model by default. Run with:
    #   FIRM_BOT_BENCH_RERANK=1 python -m eval.compare
    if os.environ.get("FIRM_BOT_BENCH_RERANK") == "1":
        ce = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        for case in cases:
            t0 = time.perf_counter()
            hits, _ = _search("firm_bot", firm_bm25, firm_idx, firm_ids, firm_vecs, case.question)
            ce_hits = [
                RetrievalHit(
                    chunk_id=h.chunk_id,
                    text=h.text,
                    metadata=h.metadata,
                    score=h.score,
                )
                for h in hits
            ]
            ce_hits = rerank(ce_hits, case.question, ce)
            ms = (time.perf_counter() - t0) * 1000
            top_hit = ce_hits[0] if ce_hits else None
            source_match = any(
                case.expected_source.lower() in str(h.metadata.get("source_name", "")).lower()
                for h in ce_hits
            )
            if case.expected_keywords and ce_hits:
                kw_cov = max(
                    sum(1 for kw in case.expected_keywords if kw.lower() in h.text.lower())
                    / len(case.expected_keywords)
                    for h in ce_hits
                )
            else:
                kw_cov = 1.0
            rows.append(
                BenchRow(
                    question=case.question,
                    chunker="firm_bot+rerank",
                    expected_source=case.expected_source,
                    precision_at_k=1.0 if source_match else 0.0,
                    keyword_coverage=kw_cov,
                    retrieval_ms=ms,
                    top_hit_id=top_hit.chunk_id if top_hit else "",
                    top_hit_source=str(top_hit.metadata.get("source_name", "?")) if top_hit else "?",
                )
            )
    return _aggregate(rows)


# ---- CLI ---------------------------------------------------------------


def _write_markdown(report: BenchReport, out: Path) -> None:
    chunkers = list(report.mean_precision_at_k.keys())
    lines = [
        "# firm-bot benchmark vs naive baseline",
        "",
        "## Aggregate",
        "",
        "| Chunker | mean precision@k | mean keyword coverage | p50 retrieval | p95 retrieval |",
        "|---------|------------------|----------------------|---------------|---------------|",
    ]
    for c in chunkers:
        lines.append(
            f"| `{c}` | {report.mean_precision_at_k[c]:.3f} | "
            f"{report.mean_keyword_coverage[c]:.3f} | "
            f"{report.p50_retrieval_ms[c]:.1f} ms | "
            f"{report.p95_retrieval_ms[c]:.1f} ms |"
        )
    out.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="eval/compare_fixture.json")
    parser.add_argument("--corpus", default="eval/compare_corpus")
    parser.add_argument("--out", default="eval/compare_results.json")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--k", type=int, default=6)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    # use the same embedder the chat uses
    from firm_bot.config import RootConfig

    root = RootConfig(data_dir="./data")
    embedder = get_embedder(root)

    report = run_benchmark(
        fixture_path=Path(args.fixture),
        corpus_dir=Path(args.corpus),
        embedder=embedder,
        k=args.k,
    )

    out_path = Path(args.out)
    out_path.write_text(json.dumps(report.as_dict(), indent=2))
    print(f"wrote {out_path}")

    if args.markdown:
        md_path = out_path.with_suffix(".md")
        _write_markdown(report, md_path)
        print(f"wrote {md_path}")

    print("\nAggregate:")
    for c in report.mean_precision_at_k:
        print(
            f"  {c}: precision@k={report.mean_precision_at_k[c]:.3f}  "
            f"keyword_cov={report.mean_keyword_coverage[c]:.3f}  "
            f"p50={report.p50_retrieval_ms[c]:.1f}ms  "
            f"p95={report.p95_retrieval_ms[c]:.1f}ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
