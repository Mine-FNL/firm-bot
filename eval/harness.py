"""Faithfulness eval harness — pure logic, no I/O.

Imports of firm_bot modules happen lazily inside ``run`` so this module
can be imported without sentence-transformers / chromadb loaded (useful
for unit tests).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def run(slug: str, fixture_path: str | Path, data_dir: str | Path | None = None) -> dict[str, Any]:
    """Run the eval and return the aggregate + per-case rows."""
    from firm_bot.answer.guard import answer_with_ollama, verify_citations
    from firm_bot.answer.prompt import build_messages, extract_cited_sources
    from firm_bot.api.embed_cache import get_embedder
    from firm_bot.config import RootConfig
    from firm_bot.retrieve.hybrid import hybrid_search
    from firm_bot.store import Store

    if data_dir is None:
        import os
        data_dir = os.environ.get("FIRM_BOT_DATA_DIR", "./data")
    cfg_path = Path(data_dir) / "config.yaml"
    root = RootConfig.load(cfg_path) if cfg_path.exists() else RootConfig(data_dir=str(data_dir))

    fixture = json.loads(Path(fixture_path).read_text())
    cases = fixture.get("cases") or []
    if not cases:
        return {"aggregate": {"cases": 0}, "rows": []}

    store = Store.open(root, slug)
    embedder = get_embedder(root)
    model = store.config.llm_model or root.llm_model
    rows: list[dict[str, Any]] = []
    for case in cases:
        q = case["question"]
        expected_sources = case.get("expected_sources") or []
        expected_keywords = case.get("expected_keywords") or []
        hits = hybrid_search(
            store=store,
            query=q,
            embed=embedder.embed,
            bm25_weight=root.hybrid_bm25_weight,
            dense_weight=root.hybrid_dense_weight,
            k=root.answer_k,
        )
        if not hits:
            rows.append({"question": q, "pass": False})
            continue
        messages = build_messages(store.config.effective_system_prompt(root), q, hits)
        answer = answer_with_ollama(root.ollama_host, model, messages, root.llm_timeout_s)
        cited = extract_cited_sources(answer)
        s_cov = sum(1 for s in expected_sources if any(s in c for c in cited)) / max(len(expected_sources), 1)
        k_cov = sum(1 for k in expected_keywords if k.lower() in answer.lower()) / max(len(expected_keywords), 1)
        sources_for_judge = [(f"[{h.metadata.get('source_name', '?')}:{h.metadata.get('page', '?')}]", h.text) for h in hits]
        ann = verify_citations(answer, sources_for_judge, root.ollama_host, root.llm_judge_model, root.llm_timeout_s)
        rows.append({
            "question": q,
            "cited": cited,
            "source_coverage": round(s_cov, 3),
            "keyword_coverage": round(k_cov, 3),
            "issues": len(ann.issues),
            "pass": s_cov >= 0.5 and k_cov >= 0.5 and len(ann.issues) == 0,
        })
    n = len(rows)
    agg = {
        "cases": n,
        "pass_rate": round(sum(1 for r in rows if r.get("pass")) / max(n, 1), 3),
        "avg_source_coverage": round(sum(r.get("source_coverage", 0) for r in rows) / max(n, 1), 3),
        "avg_keyword_coverage": round(sum(r.get("keyword_coverage", 0) for r in rows) / max(n, 1), 3),
        "avg_issues": round(sum(r.get("issues", 0) for r in rows) / max(n, 1), 2),
    }
    return {"aggregate": agg, "rows": rows}
