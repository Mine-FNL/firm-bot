# Benchmarks

Two benchmarks ship with firm-bot. Both live under `eval/`.

## Retrieval benchmark (`python -m eval.compare`)

Measures retrieval precision@k and keyword coverage over the
top-k chunks. **Does not require Ollama** — pure in-memory BM25 +
dense over the chunk corpus.

### Corpus and fixture

`eval/make_compare_corpus.py` generates a synthetic corpus of 30
contracts covering MSAs, NDAs, employment agreements, audit letters,
settlement agreements, licensing, real estate, partnerships, supply,
insurance, marketing, DPAs, and LOIs. The matching fixture
(`eval/compare_fixture.json`) has 59 questions.

### Run

```bash
python eval/make_compare_corpus.py    # one-time
python -m eval.compare --markdown     # firm_bot vs naive
FIRM_BOT_BENCH_RERANK=1 python -m eval.compare --markdown  # + rerank column
```

### Latest run (Apple M4, all-MiniLM-L6-v2)

| Method                | precision@k | keyword_cov | p50    | p95    |
|-----------------------|-------------|-------------|--------|--------|
| `firm_bot`            | **0.627**   | 0.605       | 4.5 ms | 6.5 ms |
| `naive` (sliding window) | 0.610     | **0.619**   | 4.1 ms | 5.2 ms |
| `firm_bot + rerank`   | 0.627       | 0.605       | 16 ms  | 96.9 ms |

How to read this:

- **firm_bot beats naive on precision** (+1.7 pp): structure-aware
  chunking puts the right clause in the top-k more often.
- **naive edges firm_bot on keyword coverage** (−1.4 pp): sliding-window
  can accidentally keep related clauses together when firm-bot's
  section split fragments them.
- **Reranker doesn't help on this fixture**: when BM25+dense already
  rank correctly, the reranker adds latency (p95 6.5 → 96.9 ms)
  without accuracy gain. Enable it for harder corpora where
  cross-document disambiguation matters.

Both methods plateau around 0.6 on this fixture, which is honest:
RAG over synthetic contracts is harder than it looks.

## End-to-end benchmark (`python -m eval.eval_e2e`)

Measures the **full pipeline** through Ollama: retrieve → prompt the
LLM with the citation-required system prompt → run the guard.

### Run

Requires a live Ollama. Use `--limit N` for fast iteration:

```bash
python -m eval.eval_e2e --model qwen2.5-coder:7b --limit 10 --markdown
```

### Latest run (10-question sample, 7B model)

| Metric | Value |
|--------|-------|
| headline pass rate (correct + cited + clean) | 0.000 |
| avg keyword coverage in answer | **0.750** |
| avg guard issues per case | 1.00 |
| citation coverage | **1.000** |
| p50 answer latency | 1.37 s |
| p50 guard latency | 3.62 s |

How to read this:

- **100% citation coverage**: every answer carries a `[file:page]`
  marker. The citation-required prompt is doing its job.
- **75% keyword coverage**: the LLM summarises instead of reciting
  exact phrasing on 25% of expected keywords. A real legal user
  would still find the answer; a strict substring check fails.
- **7B judge over-flags**: every case has ≥ 1 guard issue. Treat
  guard output as advisory, not as a fail/pass gate.
- **Headline 0%**: strict pass criterion
  (`keyword ≥ 0.99 ∧ cited ∧ issues == 0 ∧ correct_source`) fails on
  all 10 because every case has a guard issue. Relax the guard
  criterion and the headline tracks keyword coverage (~75%).

The benchmark does not require GPU and runs in ~5 min for 10 cases
on an M4. For the full 59-question run, plan for ~50 min.

## Benchmark methodology notes

Both benchmarks use the same 30-document / 59-question fixture but
serve different purposes:

- `eval.compare` is **fast** (seconds, no Ollama) and measures the
  retrieval layer in isolation. Use it during chunker development.
- `eval.eval_e2e` is **slow** (minutes, requires Ollama) and
  measures the full system. Use it after a meaningful change
  (chunker fix, new retrieval signal, new prompt) and before
  shipping a release.

Neither replaces a real-pilot evaluation against an actual firm's
corpus. Run both as CI gates; treat customer feedback as the
ultimate signal.
