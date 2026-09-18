"""Command-line interface for firm-bot.

Subcommands mirror the API:

    firm-bot firm create --slug acme --name "Acme LLP"
    firm-bot firm list
    firm-bot firm config acme --system-prompt-file prompt.md

    firm-bot ingest acme                # scan source/, extract, embed, index
    firm-bot query acme "what's the cap?"
    firm-bot eval acme --fixture cases.json

    firm-bot serve --host 127.0.0.1 --port 7860

Each subcommand is a small argparse subparser so the surface stays
discoverable via ``firm-bot --help``.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import FirmConfig, RootConfig, is_valid_slug


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse tree for the firm-bot CLI."""
    parser = argparse.ArgumentParser(
        prog="firm-bot",
        description="Multi-tenant local-first chatbot builder.",
    )
    parser.add_argument("--data-dir", default=None, help="override RootConfig.data_dir (default: $FIRM_BOT_DATA_DIR or ./data)")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # firm create / list / config
    p_firm = sub.add_parser("firm", help="manage firms")
    fs = p_firm.add_subparsers(dest="firm_cmd", required=True)
    pc = fs.add_parser("create", help="create a firm")
    pc.add_argument("--slug", required=True)
    pc.add_argument("--name", required=True)
    pc.add_argument("--system-prompt", default="")
    pc.add_argument("--llm-model", default="")
    pc.add_argument("--contact-email", default="")
    _pl = fs.add_parser("list", help="list firms")
    pcfg = fs.add_parser("config", help="view/edit firm config")
    pcfg.add_argument("slug")
    pcfg.add_argument("--set-system-prompt-file", default=None)
    pcfg.add_argument("--set-llm-model", default=None)
    pcfg.add_argument("--set-name", default=None)

    # ingest
    pi = sub.add_parser("ingest", help="ingest a firm's source/ directory")
    pi.add_argument("slug")

    # query
    pq = sub.add_parser("query", help="ask a single question")
    pq.add_argument("slug")
    pq.add_argument("question")
    pq.add_argument("--no-guard", action="store_true")
    pq.add_argument("--k", type=int, default=None)

    # eval
    pe = sub.add_parser("eval", help="run faithfulness eval over a fixture")
    pe.add_argument("slug")
    pe.add_argument("--fixture", required=True, help="path to JSON fixture")

    # migrate
    pm = sub.add_parser(
        "migrate",
        help="upgrade a firm's config to the current schema, preserving user values",
    )
    pm.add_argument("slug")

    # watch
    pw = sub.add_parser("watch", help="auto re-ingest when source/ changes")
    pw.add_argument("slug")
    pw.add_argument("--debounce", type=float, default=2.0, help="seconds to wait after a change")

    # serve
    ps = sub.add_parser("serve", help="run the FastAPI server")
    ps.add_argument("--host", default="127.0.0.1")
    ps.add_argument("--port", type=int, default=7860)
    ps.add_argument("--reload", action="store_true")

    # demo — bundle sample firm setup
    pd = sub.add_parser(
        "demo",
        help="bundle a sample firm so `firm-bot serve` works out of the box",
    )
    pdi = pd.add_subparsers(dest="demo_cmd", required=True)
    pd_init = pdi.add_parser(
        "init",
        help="create the demo firm from bundled samples and ingest it (idempotent)",
    )
    pd_init.add_argument("--slug", default="demo", help="firm slug (default: demo)")
    pd_init.add_argument("--name", default="Demo LLP", help="firm display name")
    pd_init.add_argument(
        "--llm-model",
        default=None,
        help="override the default LLM model for this demo firm",
    )
    pd_init.add_argument(
        "--reset",
        action="store_true",
        help="wipe an existing demo firm before re-creating (destructive)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    root = _load_root(args.data_dir)

    if args.cmd == "firm":
        return _cmd_firm(args, root)
    if args.cmd == "ingest":
        return _cmd_ingest(args, root)
    if args.cmd == "query":
        return _cmd_query(args, root)
    if args.cmd == "eval":
        return _cmd_eval(args, root)
    if args.cmd == "migrate":
        return _cmd_migrate(args, root)
    if args.cmd == "watch":
        from .watcher import cmd_watch
        return cmd_watch(args, root)
    if args.cmd == "serve":
        return _cmd_serve(args, root)
    if args.cmd == "demo":
        return _cmd_demo(args, root)
    parser.error(f"unknown command: {args.cmd}")
    return 2


def _setup_logging(verbose: int) -> None:
    level = logging.WARNING - 10 * verbose
    level = max(level, logging.DEBUG)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _load_root(data_dir: str | None) -> RootConfig:
    import os
    dd = data_dir or os.environ.get("FIRM_BOT_DATA_DIR") or "./data"
    cfg_path = Path(dd) / "config.yaml"
    root = RootConfig.load(cfg_path) if cfg_path.exists() else RootConfig(data_dir=dd)
    root.save(Path(dd) / "config.yaml")
    return root


def _cmd_firm(args: argparse.Namespace, root: RootConfig) -> int:
    from .store import Store

    if args.firm_cmd == "list":
        base = Path(root.data_dir) / "firms"
        firms = []
        if base.exists():
            for e in sorted(base.iterdir()):
                if e.is_dir():
                    cfg = FirmConfig.load(e)
                    firms.append({"slug": cfg.slug, "name": cfg.name})
        print(json.dumps({"firms": firms}, indent=2))
        return 0

    if args.firm_cmd == "create":
        if not is_valid_slug(args.slug):
            print(f"invalid slug: {args.slug}", file=sys.stderr)
            return 2
        firm_dir = Path(root.data_dir) / "firms" / args.slug
        if firm_dir.exists() and any(firm_dir.iterdir()):
            print(f"firm already exists: {args.slug}", file=sys.stderr)
            return 1
        firm_dir.mkdir(parents=True, exist_ok=True)
        cfg = FirmConfig(
            slug=args.slug,
            name=args.name,
            system_prompt=args.system_prompt,
            llm_model=args.llm_model,
            contact_email=args.contact_email,
        )
        cfg.save(firm_dir)
        (firm_dir / "source").mkdir(exist_ok=True)
        print(json.dumps({"slug": cfg.slug, "name": cfg.name, "dir": str(firm_dir)}, indent=2))
        return 0

    if args.firm_cmd == "config":
        store = Store.open(root, args.slug)
        if args.set_system_prompt_file:
            store.config.system_prompt = Path(args.set_system_prompt_file).read_text()
            store.config.save(store.firm_dir)
        if args.set_llm_model:
            store.config.llm_model = args.set_llm_model
            store.config.save(store.firm_dir)
        if args.set_name:
            store.config.name = args.set_name
            store.config.save(store.firm_dir)
        print(json.dumps(store.config.__dict__, indent=2))
        return 0
    return 2


def _cmd_ingest(args: argparse.Namespace, root: RootConfig) -> int:
    from .api.embed_cache import get_embedder
    from .store import Store

    store = Store.open(root, args.slug)
    _ingest_source_dir(root, store, get_embedder(root))
    return 0


def _ingest_source_dir(
    root: RootConfig,
    store: Any,
    embedder: Any,
) -> int:
    """Shared ingest loop used by `firm-bot ingest` and `firm-bot demo init`.

    Walks `store.source_dir`, extracts chunks, embeds them, upserts into
    Chroma, and persists BM25. Prints a summary JSON to stdout. Returns
    the number of chunks indexed.
    """
    from .chunk import chunk_documents
    from .ingest.common import IngestStats, dispatch, walk_source_dir

    all_chunks: list[Any] = []
    stats = IngestStats()
    for src in walk_source_dir(store.source_dir):
        stats.files_total += 1
        documents = dispatch(src)
        if not documents:
            stats.files_failed += 1
            continue
        store.save_processed(src, documents)
        chunks = chunk_documents(documents, chunk_size=root.chunk_size, overlap=root.chunk_overlap)
        all_chunks.extend(chunks)
        stats.documents_total += len(documents)
    if not all_chunks:
        print(json.dumps({"stats": stats.as_dict(), "chunks_indexed": 0, "warning": "no chunks produced"}, indent=2))
        return 0
    texts = [c.text for c in all_chunks]
    embeddings = embedder.embed(texts)
    store.upsert_chunks(all_chunks, embeddings)
    store.save_bm25(all_chunks)
    print(json.dumps({"stats": stats.as_dict(), "chunks_indexed": len(all_chunks)}, indent=2))
    return len(all_chunks)


def _cmd_query(args: argparse.Namespace, root: RootConfig) -> int:
    from .answer.guard import answer_with_ollama, verify_citations
    from .answer.prompt import build_messages, extract_cited_sources
    from .api.embed_cache import get_embedder
    from .retrieve.hybrid import hybrid_search
    from .store import Store

    store = Store.open(root, args.slug)
    embedder = get_embedder(root)
    if store.collection().count() == 0:
        print("error: firm has no indexed chunks; run `firm-bot ingest <slug>` first", file=sys.stderr)
        return 2
    hits = hybrid_search(
        store=store,
        query=args.question,
        embed=embedder.embed,
        bm25_weight=root.hybrid_bm25_weight,
        dense_weight=root.hybrid_dense_weight,
        k=args.k or root.answer_k,
    )
    if not hits:
        print(json.dumps({"answer": "I don't know — no relevant chunks were retrieved.", "hits": []}, indent=2))
        return 0
    model = store.config.llm_model or root.llm_model
    system = store.config.effective_system_prompt(root)
    messages = build_messages(system, args.question, hits)
    answer = answer_with_ollama(root.ollama_host, model, messages, root.llm_timeout_s)
    cited = extract_cited_sources(answer)
    out = {
        "answer": answer,
        "cited": cited,
        "hits": [
            {"chunk_id": h.chunk_id, "marker": h.metadata.get("source_name"), "score": round(h.score, 4),
             "bm25_rank": h.bm25_rank, "dense_rank": h.dense_rank}
            for h in hits
        ],
        "model": model,
    }
    if not args.no_guard:
        sources_for_judge = [(f"[{h.metadata.get('source_name', '?')}:{h.metadata.get('page', '?')}]", h.text) for h in hits]
        ann = verify_citations(answer, sources_for_judge, root.ollama_host, root.llm_judge_model, root.llm_timeout_s)
        out["issues"] = [i.to_dict() for i in ann.issues]
        out["summary"] = ann.summary
    print(json.dumps(out, indent=2))
    return 0


def _cmd_eval(args: argparse.Namespace, root: RootConfig) -> int:

    from .answer.guard import answer_with_ollama, verify_citations
    from .answer.prompt import build_messages, extract_cited_sources
    from .api.embed_cache import get_embedder
    from .retrieve.hybrid import hybrid_search
    from .store import Store

    fixture = json.loads(Path(args.fixture).read_text())
    cases = fixture.get("cases") or []
    if not cases:
        print("error: fixture has no cases", file=sys.stderr)
        return 2
    store = Store.open(root, args.slug)
    embedder = get_embedder(root)
    model = store.config.llm_model or root.llm_model
    rows = []
    for case in cases:
        q = case["question"]
        expected_sources = case.get("expected_sources") or []
        expected_keywords = case.get("expected_keywords") or []
        hits = hybrid_search(
            store=store, query=q, embed=embedder.embed,
            bm25_weight=root.hybrid_bm25_weight, dense_weight=root.hybrid_dense_weight,
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
    print(json.dumps({"aggregate": agg, "rows": rows}, indent=2))
    return 0


def _cmd_migrate(args: argparse.Namespace, root: RootConfig) -> int:
    """Upgrade a firm's config.yaml to the current schema.

    New fields are added with sensible defaults; existing user-set
    values are preserved. Backups are written to ``config.yaml.bak``
    before any modification.
    """
    from .store import Store

    store = Store.open(root, args.slug)
    cfg_path = store.firm_dir / "config.yaml"
    if not cfg_path.exists():
        print(f"no config at {cfg_path}", file=sys.stderr)
        return 1
    backup = cfg_path.with_name(cfg_path.name + ".bak")
    backup.write_text(cfg_path.read_text())
    cfg = FirmConfig.load(store.firm_dir)
    cfg.validate()
    cfg.save(store.firm_dir)
    print(
        json.dumps(
            {
                "firm": args.slug,
                "config_path": str(cfg_path),
                "backup": str(backup),
                "fields": sorted(cfg.__dict__.keys()),
            },
            indent=2,
        )
    )
    return 0


def _cmd_serve(args: argparse.Namespace, root: RootConfig) -> int:
    import os
    os.environ.setdefault("FIRM_BOT_DATA_DIR", root.data_dir)
    import uvicorn
    uvicorn.run(
        "firm_bot.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def _cmd_demo(args: argparse.Namespace, root: RootConfig) -> int:
    """`firm-bot demo init` — one-shot bootstrap of the bundled sample firm.

    Idempotent: re-running over an existing demo firm is a no-op
    unless --reset is passed (which wipes the firm first).
    """
    if args.demo_cmd != "init":
        return 2  # argparse would have caught unknown subcommands

    samples_root = Path(__file__).resolve().parent.parent / "examples" / "sample_data"
    if not samples_root.is_dir():
        print(
            f"error: bundled sample data not found at {samples_root}",
            file=sys.stderr,
        )
        return 1

    firm_dir = Path(root.data_dir) / "firms" / args.slug

    # Optional destructive reset
    if args.reset and firm_dir.exists():
        import shutil
        shutil.rmtree(firm_dir)
        print(f"removed existing firm: {firm_dir}")

    # Create firm if missing
    firm_cfg_path = firm_dir / "config.yaml"
    if not firm_cfg_path.exists():
        from .config import FirmConfig
        cfg = FirmConfig(slug=args.slug, name=args.name)
        if args.llm_model:
            cfg.llm_model = args.llm_model
        cfg.save(firm_dir)
        print(f"created firm {args.slug!r} ({args.name})")
    else:
        print(f"firm {args.slug!r} already exists")

    # Copy bundled samples into the firm's source/ directory
    from .store import Store
    store = Store.open(root, args.slug)
    copied: list[str] = []
    for src in sorted(samples_root.glob("*.pdf")):
        target_path = store.source_dir / src.name
        if not target_path.exists():
            target_path.write_bytes(src.read_bytes())
            copied.append(src.name)
    if copied:
        print(f"copied {len(copied)} sample(s): {', '.join(copied)}")
    else:
        print("source/ already has the bundled samples")

    # Reuse the same ingest pipeline as `firm-bot ingest`
    from .api.embed_cache import get_embedder
    indexed = _ingest_source_dir(root, store, get_embedder(root))

    print(json.dumps(
        {
            "chunks_indexed": indexed,
            "ready_for": f"firm-bot query {args.slug} \"What's the cap on liability?\"",
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
