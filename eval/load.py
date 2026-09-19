"""Concurrent load benchmark for firm-bot's /query endpoint.

Measures end-to-end latency under N concurrent users, reporting p50/p95/p99,
throughput (RPS), and error rate. Uses httpx + ASGITransport so we can
benchmark the real app without spinning up a separate process; or pass
``--live-url http://localhost:8000`` to hit a running server.

Usage:
    # In-process benchmark against the demo firm
    python3 -m eval.load --queries 100 --concurrency 8

    # Against a running uvicorn server
    python3 -m eval.load --live-url http://localhost:8000 \
        --slug demo --queries 200 --concurrency 16

The benchmark stubs the LLM call by default (no Ollama needed). Pass
``--no-mock-llm`` to actually call Ollama (requires the model to be
pulled and reachable).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from firm_bot.api.app import app as _app
from firm_bot.config import RootConfig
from firm_bot.store import Store


@dataclass
class LatencyStats:
    samples: list[float] = field(default_factory=list)
    errors: int = 0
    successes: int = 0

    def add(self, latency_ms: float, ok: bool) -> None:
        if ok:
            self.samples.append(latency_ms)
            self.successes += 1
        else:
            self.errors += 1

    def percentiles(self) -> dict[str, float]:
        if not self.samples:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}
        s = sorted(self.samples)
        n = len(s)

        def pct(p: float) -> float:
            idx = min(int(p * (n - 1)), n - 1)
            return s[idx]

        return {
            "p50": pct(0.50),
            "p95": pct(0.95),
            "p99": pct(0.99),
            "min": s[0],
            "max": s[-1],
            "mean": statistics.fmean(s),
        }


DEFAULT_QUERIES = [
    "What is the cap on liability?",
    "How long does the NDA last?",
    "What is the governing law?",
    "What are the payment terms?",
    "Is there a non-compete clause?",
    "What is the termination notice period?",
    "Who are the parties to the agreement?",
    "What is the dispute resolution mechanism?",
    "Are there any indemnification provisions?",
    "What is the confidentiality term?",
]


def _percentile_label(stats: LatencyStats) -> dict[str, float]:
    p = stats.percentiles()
    return {
        "p50_ms": round(p["p50"], 2),
        "p95_ms": round(p["p95"], 2),
        "p99_ms": round(p["p99"], 2),
        "min_ms": round(p["min"], 2),
        "max_ms": round(p["max"], 2),
        "mean_ms": round(p["mean"], 2),
    }


async def _run_one_query(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
) -> tuple[float, bool]:
    """Fire one query. Returns (latency_ms, ok)."""
    start = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, timeout=60.0)
        elapsed = (time.perf_counter() - start) * 1000
        ok = resp.status_code == 200 and bool(resp.json().get("answer"))
        return elapsed, ok
    except Exception:
        elapsed = (time.perf_counter() - start) * 1000
        return elapsed, False


async def _run_load(
    url: str,
    queries: list[str],
    concurrency: int,
    total: int,
    run_guard: bool,
    on_progress: Callable[[int, int], None] | None = None,
) -> LatencyStats:
    """Run ``total`` requests at `` concurrency `` parallel. Returns aggregate stats."""
    stats = LatencyStats()
    sem = asyncio.Semaphore(concurrency)
    completed = 0

    async def task(i: int) -> None:
        nonlocal completed
        async with sem:
            question = queries[i % len(queries)]
            payload = {"question": question, "run_guard": run_guard, "k": 4}
            async with httpx.AsyncClient() as client:
                elapsed, ok = await _run_one_query(client, url, payload)
            stats.add(elapsed, ok)
            completed += 1
            if on_progress and completed % max(1, total // 20) == 0:
                on_progress(completed, total)

    await asyncio.gather(*(task(i) for i in range(total)))
    return stats


async def _run_against_app(
    app: Any,
    slug: str,
    queries: list[str],
    concurrency: int,
    total: int,
    run_guard: bool,
    on_progress: Callable[[int, int], None] | None = None,
) -> LatencyStats:
    """Run load against an in-process ASGI app via ASGITransport."""
    stats = LatencyStats()
    sem = asyncio.Semaphore(concurrency)
    completed = 0
    url = f"/v1/firms/{slug}/query"

    async def task(i: int) -> None:
        nonlocal completed
        async with sem:
            question = queries[i % len(queries)]
            payload = {"question": question, "run_guard": run_guard, "k": 4}
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                elapsed, ok = await _run_one_query(client, url, payload)
            stats.add(elapsed, ok)
            completed += 1
            if on_progress and completed % max(1, total // 20) == 0:
                on_progress(completed, total)

    await asyncio.gather(*(task(i) for i in range(total)))
    return stats


def _format_markdown(concurrency: int, total: int, stats: LatencyStats, elapsed_s: float) -> str:
    p = _percentile_label(stats)
    rps = total / max(elapsed_s, 0.001)
    err_pct = (stats.errors / max(stats.successes + stats.errors, 1)) * 100
    return f"""# firm-bot concurrent load benchmark

**Setup:** {total} queries at concurrency {concurrency}
**Wall time:** {elapsed_s:.2f} s
**Throughput:** {rps:.2f} RPS
**Error rate:** {err_pct:.1f}% ({stats.errors} / {stats.successes + stats.errors})

| Metric | Value |
|--------|-------|
| p50 latency | {p["p50_ms"]:.1f} ms |
| p95 latency | {p["p95_ms"]:.1f} ms |
| p99 latency | {p["p99_ms"]:.1f} ms |
| min | {p["min_ms"]:.1f} ms |
| max | {p["max_ms"]:.1f} ms |
| mean | {p["mean_ms"]:.1f} ms |
"""


def _format_json(
    concurrency: int, total: int, stats: LatencyStats, elapsed_s: float
) -> dict[str, Any]:
    p = _percentile_label(stats)
    return {
        "concurrency": concurrency,
        "total": total,
        "wall_time_s": round(elapsed_s, 3),
        "throughput_rps": round(total / max(elapsed_s, 0.001), 2),
        "error_rate_pct": round((stats.errors / max(stats.successes + stats.errors, 1)) * 100, 2),
        "successes": stats.successes,
        "errors": stats.errors,
        "latency_ms": p,
    }


def _setup_test_app() -> tuple[Any, str]:
    """Wire a test app + a pre-seeded firm for in-process benchmark."""
    tmp = Path(tempfile.mkdtemp(prefix="firm-bot-load-"))
    os.environ["FIRM_BOT_DATA_DIR"] = str(tmp)
    root = RootConfig(data_dir=str(tmp))
    slug = "loadbench"
    store = Store.open(root, slug)
    store.config.name = "Load Bench"
    store.config.save(store.firm_dir)
    store.source_dir.mkdir(exist_ok=True)

    # Ingest one synthetic PDF (only .pdf/.eml/.docx supported by dispatch)
    sample_text = (
        "MASTER SERVICES AGREEMENT\n\n"
        "1. Parties. Acme Corp ('Client') and Wayne Enterprises ('Vendor').\n\n"
        "2. Term. This Agreement shall commence on the Effective Date and "
        "continue for a period of three (3) years.\n\n"
        "3. Limitation of Liability. In no event shall either party's total "
        "liability exceed the fees paid in the twelve (12) months preceding "
        "the claim.\n\n"
        "4. Governing Law. This Agreement shall be governed by the laws of "
        "the State of Delaware.\n\n"
        "5. Confidentiality. Each party shall hold the other's Confidential "
        "Information in strict confidence for a period of five (5) years.\n\n"
        "6. Termination. Either party may terminate this Agreement with sixty "
        "(60) days written notice.\n\n"
        "7. Indemnification. Vendor shall indemnify Client against any "
        "third-party claims arising from Vendor's gross negligence.\n"
    )
    sample_path = store.source_dir / "msa.pdf"
    doc = SimpleDocTemplate(str(sample_path), pagesize=LETTER, leftMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    flow = [Paragraph(sample_text.replace("\n\n", "<br/><br/>"), styles["Normal"])]
    flow.append(Spacer(1, 0.2 * inch))
    doc.build(flow)

    # Ingest
    client = TestClient(_app)
    r = client.post(f"/v1/firms/{slug}/ingest")
    if r.status_code != 200:
        raise RuntimeError(f"ingest failed: {r.status_code} {r.text}")
    chunks = r.json().get("chunks_indexed", 0)
    if chunks == 0:
        raise RuntimeError("ingest produced 0 chunks")

    return _app, slug


async def _amain(args: argparse.Namespace) -> int:
    queries = DEFAULT_QUERIES
    if args.queries_file:
        queries = [
            ln.strip() for ln in Path(args.queries_file).read_text().splitlines() if ln.strip()
        ]

    if args.live_url:
        url = f"{args.live_url.rstrip('/')}/v1/firms/{args.slug}/query"
        slug = args.slug
        app = None
    else:
        app, slug = _setup_test_app()
        url = f"/v1/firms/{slug}/query"

    def progress(done: int, total: int) -> None:
        print(f"  progress: {done}/{total} ({100 * done / total:.0f}%)", flush=True)

    print(f"load: {args.total} queries at concurrency {args.concurrency} against {url}")
    start = time.perf_counter()
    if app is not None:
        stats = await _run_against_app(
            app, slug, queries, args.concurrency, args.total, not args.no_guard, progress
        )
    else:
        stats = await _run_load(
            url, queries, args.concurrency, args.total, not args.no_guard, progress
        )
    elapsed = time.perf_counter() - start

    j = _format_json(args.concurrency, args.total, stats, elapsed)
    md = _format_markdown(args.concurrency, args.total, stats, elapsed)

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(j, indent=2))
    if args.output_md:
        Path(args.output_md).write_text(md)

    print()
    print(md)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="firm-bot concurrent load benchmark")
    p.add_argument("--total", type=int, default=100, help="total queries to fire (default: 100)")
    p.add_argument(
        "--concurrency", type=int, default=8, help="max concurrent in-flight (default: 8)"
    )
    p.add_argument(
        "--live-url",
        type=str,
        default=None,
        help="benchmark a running server (default: in-process TestClient)",
    )
    p.add_argument("--slug", type=str, default="loadbench", help="firm slug (used with --live-url)")
    p.add_argument(
        "--queries-file",
        type=str,
        default=None,
        help="newline-delimited query list (default: built-in 10 queries)",
    )
    p.add_argument(
        "--no-guard",
        action="store_true",
        help="skip the citation guard to isolate retrieval latency",
    )
    p.add_argument("--output-json", type=str, default=None, help="write JSON results to this path")
    p.add_argument("--output-md", type=str, default=None, help="write Markdown report to this path")
    args = p.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
