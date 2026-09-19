"""End-to-end faithfulness benchmark.

This is the missing measurement. ``eval.compare`` measures retrieval
in isolation (BM25 + dense ranking without an LLM in the loop); this
benchmark runs the FULL firm-bot pipeline — retrieve, prompt the
LLM with the citation-required system prompt, run the guard model —
and reports how often the answer:

1. **contains every expected keyword** (proxy for correctness)
2. **cites a real source** (proxy for grounding)
3. **passes the guard with zero issues** (proxy for non-hallucination)
4. **is correct + cited + clean** all at once (the headline number)

Requires a live Ollama. Run with::

    python -m eval.eval_e2e --model qwen2.5-coder:7b --markdown

If you don't have Ollama running, the script exits cleanly with a
``SKIPPED`` line — it's purely opt-in.

Numbers from a real run go into the README's "End-to-end benchmark"
section.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("eval.eval_e2e")


@dataclass
class E2ERow:
    question: str
    expected_source: str
    expected_keywords: list[str]
    answer: str
    cited: list[str]
    issues: int
    keyword_coverage: float  # fraction of expected keywords in answer
    has_citation: bool
    source_correct: bool  # did the citation point to the expected source
    answer_seconds: float
    guard_seconds: float
    ragas_faithfulness: float  # NaN if not computable
    ragas_answer_relevancy: float
    ragas_context_precision: float
    ragas_context_recall: float  # NaN if no ground truth


@dataclass
class E2EReport:
    cases: int
    rows: list[E2ERow]
    p50_answer_s: float
    p95_answer_s: float
    p50_guard_s: float
    p95_guard_s: float
    headline_pass_rate: float  # correct + cited + clean
    avg_keyword_coverage: float
    avg_guard_issues: float
    citation_coverage: float
    avg_ragas_faithfulness: float
    avg_ragas_answer_relevancy: float
    avg_ragas_context_precision: float
    model: str
    judge_model: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "cases": self.cases,
            "p50_answer_s": round(self.p50_answer_s, 2),
            "p95_answer_s": round(self.p95_answer_s, 2),
            "p50_guard_s": round(self.p50_guard_s, 3),
            "p95_guard_s": round(self.p95_guard_s, 3),
            "headline_pass_rate": round(self.headline_pass_rate, 3),
            "avg_keyword_coverage": round(self.avg_keyword_coverage, 3),
            "avg_guard_issues": round(self.avg_guard_issues, 2),
            "citation_coverage": round(self.citation_coverage, 3),
            "avg_ragas_faithfulness": round(self.avg_ragas_faithfulness, 3),
            "avg_ragas_answer_relevancy": round(self.avg_ragas_answer_relevancy, 3),
            "avg_ragas_context_precision": round(self.avg_ragas_context_precision, 3),
            "model": self.model,
            "judge_model": self.judge_model,
            "rows": [asdict(r) for r in self.rows],
        }


def _check_ollama(host: str) -> bool:
    """Quick health-check; return True if Ollama is reachable."""
    import httpx

    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(f"{host.rstrip('/')}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


# allowed in this module: heavy lazy imports + the main loop is necessarily long


def run_e2e(
    fixture_path: Path,
    corpus_dir: Path,
    ollama_host: str,
    answer_model: str,
    judge_model: str,
    k: int = 6,
    chunk_size: int = 1200,
) -> E2EReport:
    """Run the full pipeline on every question and report aggregate metrics."""
    from firm_bot.answer.guard import answer_with_ollama, verify_citations
    from firm_bot.answer.prompt import build_messages, extract_cited_sources
    from firm_bot.api.embed_cache import get_embedder
    from firm_bot.chunk import chunk_documents
    from firm_bot.config import RootConfig
    from firm_bot.ingest.common import dispatch
    from firm_bot.retrieve.hybrid import hybrid_search
    from firm_bot.store import Store

    from .ragas import make_ollama_fn, score_all

    if not _check_ollama(ollama_host):
        print(
            f"SKIPPED: Ollama not reachable at {ollama_host}. Start Ollama and re-run.",
            file=sys.stderr,
        )
        sys.exit(2)

    fixture = json.loads(fixture_path.read_text())
    cases = fixture.get("cases") or []
    if not cases:
        raise SystemExit("fixture has no cases")

    # ---- set up an in-memory firm pointing at the corpus ----
    root = RootConfig(data_dir="./data", llm_model=answer_model, llm_judge_model=judge_model)
    store = Store.open(root, "bench")
    sources = sorted(corpus_dir.rglob("*.pdf")) + sorted(corpus_dir.rglob("*.docx"))
    all_docs = []
    for s in sources:
        all_docs.extend(dispatch(s))
    chunks = chunk_documents(all_docs, chunk_size=chunk_size, overlap=200)
    embedder = get_embedder(root)
    texts = [c.text for c in chunks]
    embeddings = embedder.embed(texts)
    store.upsert_chunks(chunks, embeddings)
    store.save_bm25(chunks)

    # RAGAS wiring: judge reuses the same Ollama model the guard uses,
    # and the embedder is wrapped to a single-text callable that
    # ragas.score_answer_relevancy expects.
    ragas_ollama = make_ollama_fn(ollama_host, judge_model, root.llm_timeout_s)

    def _embed_one(text: str) -> list[float]:
        vec = embedder.embed([text])[0]
        return [float(x) for x in vec]

    rows: list[E2ERow] = []
    for i, case in enumerate(cases, 1):
        question = case["question"]
        expected_source = case["expected_source"]
        expected_keywords = case.get("expected_keywords") or []

        t0 = time.perf_counter()
        hits = hybrid_search(
            store=store,
            query=question,
            embed=embedder.embed,
            bm25_weight=root.hybrid_bm25_weight,
            dense_weight=root.hybrid_dense_weight,
            k=k,
        )
        if not hits:
            answer_text = "I don't know — no relevant chunks were retrieved."
            cited = []
            issues = 0
            ans_s = time.perf_counter() - t0
            guard_s = 0.0
        else:
            system = (
                "You are a careful assistant for a professional services firm. "
                "Answer ONLY using the provided source chunks. "
                "Cite every factual claim with the bracketed source marker exactly "
                "as shown in the context, e.g. [contract.pdf:p.4]. "
                "If the sources do not contain the answer, say so plainly — "
                "do not guess. Prefer short, direct sentences; the operator "
                "reading your output is a busy human."
            )
            messages = build_messages(system, question, hits)
            try:
                answer_text = answer_with_ollama(
                    ollama_host,
                    answer_model,
                    messages,
                    root.llm_timeout_s,
                )
            except Exception as e:
                log.warning("answer failed for case %d: %s", i, e)
                answer_text = ""
            cited = extract_cited_sources(answer_text)
            ans_s = time.perf_counter() - t0

            t1 = time.perf_counter()
            try:
                ann = verify_citations(
                    answer=answer_text,
                    sources=[
                        (
                            f"[{h.metadata.get('source_name', '?')}:p.{h.metadata.get('page', '?')}]",
                            h.text,
                        )
                        for h in hits
                    ],
                    ollama_host=ollama_host,
                    judge_model=judge_model,
                    timeout_s=root.llm_timeout_s,
                )
                issues = len(ann.issues)
            except Exception as e:
                log.warning("guard failed for case %d: %s", i, e)
                issues = 0
            guard_s = time.perf_counter() - t1

        kw_cov = (
            sum(1 for kw in expected_keywords if kw.lower() in answer_text.lower())
            / max(len(expected_keywords), 1)
            if expected_keywords
            else 1.0
        )
        has_citation = bool(cited)
        source_correct = (
            any(expected_source.lower() in c.lower() for c in cited) if cited else False
        )

        # RAGAS metrics: ``hits`` is the retrieval list (may be empty
        # if the corpus returned nothing). The judge calls are cheap
        # (1 per claim / 1 per chunk) so we run them inline; a future
        # optimisation could batch them. Each call is wrapped in
        # try/except so a single judge failure does not blow up the
        # whole benchmark — the metric collapses to NaN instead.
        if hits:
            contexts = [h.text for h in hits]
            retrieved_ids = [h.chunk_id for h in hits]
        else:
            contexts = []
            retrieved_ids = []
        # Fixture schema permits ``relevant_ids`` (preferred) or
        # ``relevant_docs`` (legacy). Either way, missing → NaN
        # for context_recall (rendered as "n/a" in the markdown).
        relevant_ids = case.get("relevant_ids") or case.get("relevant_docs") or None
        try:
            scores = score_all(
                question=question,
                answer=answer_text,
                contexts=contexts,
                retrieved_ids=retrieved_ids,
                relevant_ids=relevant_ids,
                ollama_fn=ragas_ollama,
                embed_fn=_embed_one,
            )
            faith = scores.faithfulness
            ans_rel = scores.answer_relevancy
            ctx_prec = scores.context_precision
            ctx_recall = scores.context_recall
        except Exception as e:
            log.warning("ragas scoring failed for case %d: %s", i, e)
            faith = float("nan")
            ans_rel = float("nan")
            ctx_prec = float("nan")
            ctx_recall = float("nan")

        rows.append(
            E2ERow(
                question=question,
                expected_source=expected_source,
                expected_keywords=expected_keywords,
                answer=answer_text[:400] + ("…" if len(answer_text) > 400 else ""),
                cited=cited,
                issues=issues,
                keyword_coverage=kw_cov,
                has_citation=has_citation,
                source_correct=source_correct,
                answer_seconds=ans_s,
                guard_seconds=guard_s,
                ragas_faithfulness=faith,
                ragas_answer_relevancy=ans_rel,
                ragas_context_precision=ctx_prec,
                ragas_context_recall=ctx_recall,
            )
        )
        print(
            f"[{i:3d}/{len(cases)}] kw_cov={kw_cov:.2f} cited={has_citation} "
            f"issues={issues} faith={faith:.2f} ans={ans_s:.1f}s guard={guard_s:.1f}s — {question[:50]}",
            file=sys.stderr,
        )

    n = len(rows)
    ans_times = sorted(r.answer_seconds for r in rows)
    guard_times = sorted(r.guard_seconds for r in rows)
    p50_ans = statistics.median(ans_times)
    p95_ans = ans_times[max(0, int(n * 0.95) - 1)]
    p50_g = statistics.median(guard_times)
    p95_g = guard_times[max(0, int(n * 0.95) - 1)]
    headline = (
        sum(
            1
            for r in rows
            if r.keyword_coverage >= 0.99 and r.has_citation and r.issues == 0 and r.source_correct
        )
        / n
    )
    avg_kw = statistics.mean(r.keyword_coverage for r in rows)
    avg_iss = statistics.mean(r.issues for r in rows)
    cite_cov = sum(1 for r in rows if r.has_citation) / n
    avg_faith = _nan_safe_mean(r.ragas_faithfulness for r in rows)
    avg_ans_rel = _nan_safe_mean(r.ragas_answer_relevancy for r in rows)
    avg_ctx_prec = _nan_safe_mean(r.ragas_context_precision for r in rows)

    return E2EReport(
        cases=n,
        rows=rows,
        p50_answer_s=p50_ans,
        p95_answer_s=p95_ans,
        p50_guard_s=p50_g,
        p95_guard_s=p95_g,
        headline_pass_rate=headline,
        avg_keyword_coverage=avg_kw,
        avg_guard_issues=avg_iss,
        citation_coverage=cite_cov,
        avg_ragas_faithfulness=avg_faith,
        avg_ragas_answer_relevancy=avg_ans_rel,
        avg_ragas_context_precision=avg_ctx_prec,
        model=answer_model,
        judge_model=judge_model,
    )


def _nan_safe_mean(values: Any) -> float:
    """Mean over a generator, skipping NaN. Empty / all-NaN → NaN.

    Centralised so the four RAGAS aggregate rows agree on the NaN
    convention. ``statistics.mean`` raises on an empty input and
    propagates NaN silently, both of which would corrupt the report.
    """
    nums: list[float] = []
    for v in values:
        if isinstance(v, float) and math.isnan(v):
            continue
        nums.append(float(v))
    if not nums:
        return float("nan")
    return statistics.mean(nums)


def _fmt_metric(value: float) -> str:
    """Format a metric for the markdown table; NaN renders as "n/a"."""
    if isinstance(value, float) and math.isnan(value):
        return "n/a"
    return f"{value:.3f}"


def _write_markdown(report: E2EReport, out: Path) -> None:
    lines = [
        "# firm-bot end-to-end benchmark",
        "",
        f"**{report.cases} questions**, answer model `{report.model}`, "
        f"guard `{report.judge_model}`.",
        "",
        "## Aggregate",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| **headline pass rate** (correct + cited + clean) | **{report.headline_pass_rate:.3f}** |",
        f"| avg keyword coverage in answer | {report.avg_keyword_coverage:.3f} |",
        f"| avg guard issues per case | {report.avg_guard_issues:.2f} |",
        f"| citation coverage (answer contains a marker) | {report.citation_coverage:.3f} |",
        f"| p50 answer latency | {report.p50_answer_s:.2f} s |",
        f"| p95 answer latency | {report.p95_answer_s:.2f} s |",
        f"| p50 guard latency | {report.p50_guard_s:.2f} s |",
        f"| p95 guard latency | {report.p95_guard_s:.2f} s |",
        "",
        "## RAGAS-style metrics (LLM-as-judge)",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| avg faithfulness (claims supported by retrieved context) | {_fmt_metric(report.avg_ragas_faithfulness)} |",
        f"| avg answer relevancy (cosine of answer / question embeddings) | {_fmt_metric(report.avg_ragas_answer_relevancy)} |",
        f"| avg context precision (relevant chunks / retrieved chunks) | {_fmt_metric(report.avg_ragas_context_precision)} |",
        "| avg context recall (ground-truth chunks retrieved) | n/a — fixture has no `relevant_ids` |",
        "",
    ]
    out.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="eval/compare_fixture.json")
    parser.add_argument("--corpus", default="eval/compare_corpus")
    parser.add_argument(
        "--ollama-host", default=os.environ.get("FIRM_BOT_OLLAMA_HOST", "http://127.0.0.1:11434")
    )
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--judge-model", default="qwen2.5-coder:7b")
    parser.add_argument("--out", default="eval/e2e_results.json")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument(
        "--limit", type=int, default=10, help="cap the number of cases (for fast iteration)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    # Cap the fixture size if requested
    if args.limit:
        fx = Path(args.fixture)
        full = json.loads(fx.read_text())
        full["cases"] = full["cases"][: args.limit]
        capped = fx.with_name(fx.stem + f".cap{args.limit}" + fx.suffix)
        capped.write_text(json.dumps(full, indent=2))
        args.fixture = str(capped)
        log.warning("capped fixture to first %d cases → %s", args.limit, capped)

    report = run_e2e(
        fixture_path=Path(args.fixture),
        corpus_dir=Path(args.corpus),
        ollama_host=args.ollama_host,
        answer_model=args.model,
        judge_model=args.judge_model,
        k=args.k,
    )
    Path(args.out).write_text(json.dumps(report.as_dict(), indent=2))
    print(f"wrote {args.out}")

    if args.markdown:
        md_path = Path(args.out).with_suffix(".md")
        _write_markdown(report, md_path)
        print(f"wrote {md_path}")

    print(
        f"\nheadline_pass_rate={report.headline_pass_rate:.3f}  "
        f"avg_kw_cov={report.avg_keyword_coverage:.3f}  "
        f"citation_cov={report.citation_coverage:.3f}  "
        f"avg_guard_issues={report.avg_guard_issues:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
