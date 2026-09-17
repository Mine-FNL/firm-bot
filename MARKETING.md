# firm-bot marketing kit

Everything you need to launch firm-bot in public. Pick the channels
that fit your voice; don't blast all of them at once.

> **Before you publish anything, read [`docs/marketing/DESIGN.md`](docs/marketing/DESIGN.md).**
> It locks the palette, voice, and story arc every asset below draws
> from. Mixing old and new visual identity in the same campaign is
> worse than either alone.

## Assets

All in `docs/assets/marketing/`:

| File | Purpose | Size |
|------|---------|------|
| `hero.png`            | 1600x900 — README top banner, GitHub OG variant | 112 KB |
| `architecture.png`    | 1600x1000 — six-stage pipeline explainer       | 92 KB  |
| `comparison.png`      | 1600x1000 — vs Harvey / Spellbook / Glean     | 131 KB |
| `why_local.png`       | 1600x1000 — "your data, your box" angle       | 87 KB  |
| `benchmark.png`       | 1600x900 — CUAD precision@k bar chart         | 62 KB  |
| `demo.gif`            | 1200x720 — 7-second UI walkthrough loop       | 175 KB |
| `demo.mp4`            | H.264 of the above                            | 84 KB  |
| `demo-video.mp4`      | **1920x1080 — full 66-second demo video**     | 1.0 MB |
| `social-preview.png`  | 1280x640 — set as the repo's social preview   | 84 KB  |

Regenerate any of these by running the matching `scripts/marketing/render_*.py`.

## Channels (in priority order)

1. **Hacker News** — Show HN. Highest-quality signal source.
2. **Twitter/X** — single-launch tweet + thread + GIF.
3. **Reddit** — r/LocalLLaMA first (audience overlap), then r/MachineLearning, r/Python, r/legaltech.
4. **LinkedIn** — long-form post for the professional-services audience.
5. **Dev.to** — full article with the architecture explainer.

## Channel 1 — Hacker News (Show HN)

**Title (max 80 chars):**
```
Show HN: firm-bot – local-first RAG for legal & audit, citations enforced
```

**Body:**
```
firm-bot is a local-first chatbot builder for professional services
firms (legal, audit, consultancy). You drop your firm's PDFs, EMLs,
and DOCX into a per-firm folder; it builds a chat endpoint that
answers questions with citations on every claim. Nothing leaves the
box — no cloud calls, no telemetry, no vendor.

Why I built it:
Cloud RAG (Harvey, Spellbook, Glean) is fine for general-purpose
work, but professional services firms have constraints cloud
vendors can't meet: attorney-client privilege, GDPR/HIPAA/SOC2
review, air-gapped deployments, audit trail ownership. Building
in-house means owning your chain of custody.

What's interesting (vs. the usual RAG demo):
- Structure-aware chunker recognises Article §, Section, Title Case,
  WHEREAS — closes a 0.70→0.95 precision gap vs. naive chunking on
  contracts that don't prefix sections with "Article".
- Citation-required prompt + 7B LLM-as-judge guard. Every claim
  must carry a [file:page] marker; the guard flags ungrounded
  claims. On a 10-contract CUAD subset: 0.538 precision@k vs 0.462
  naive.
- Hybrid retrieval (BM25 + dense via RRF). Reranker is opt-in
  (cross-encoder/ms-marco-MiniLM-L-6-v2); benchmark showed it
  doesn't help on this fixture, so default is no rerank.
- RAGAS-style quality metrics (faithfulness, answer_relevancy,
  context_precision, context_recall) computed without the heavy
  ragas package.
- Prometheus /metrics + structured JSON logs + request-id
  propagation, opt-in via `pip install firm-bot[observability]`.
- Per-IP rate limit, body size cap, CORS allow-list (fail-closed),
  log redaction. STRIDE threat model in SECURITY.md.
- Concurrent load benchmark. `python3 -m eval.load --total 200
  --concurrency 16` for p50/p95/p99 + throughput.

Stack: FastAPI + Chroma + BM25 + sentence-transformers +
fastembed + Ollama. Python 3.11+. MIT.

Self-host in 60 seconds:
  git clone https://github.com/Mine-FNL/firm-bot
  cd firm-bot && pip install -e ".[dev,observability]"
  firm-bot serve

Curious what HN thinks. Specifically: (1) is the citation-required
+ LLM-as-judge pattern interesting as a default, or should it be
opt-in? (2) anyone else running into "vendor RAG doesn't satisfy
our compliance review" and what did you do?
```

## Channel 2 — Twitter / X

**Launch tweet (280 chars):**
```
Just open-sourced firm-bot — local-first RAG for legal & audit.

Drop PDFs/EML/DOCX → chat endpoint with citations on every claim.
No cloud calls. No telemetry. MIT.

0.538 precision@k on CUAD subset vs 0.462 naive.
129 tests. 74% coverage. RAGAS metrics.

github.com/Mine-FNL/firm-bot
```

Attach: `demo.gif` (or `demo.mp4` if X prefers video).

**Thread (5 tweets):**

1/5 — What we built
```
firm-bot is for firms that can't put client contracts in someone
else's vector store.

Cloud RAG (Harvey, Spellbook, Glean) is great. It also can't
satisfy an in-house compliance review when the work product is
privileged.

So we built a local-first RAG you can air-gap.
```

2/5 — The interesting bits
```
The chunker is the actual hard part. Contracts don't follow
"Section 1, Section 2" — they have Article + Title Case headings
(WHEREAS, RECITALS), indented exhibits, and sectionless prose.

Our chunker recognises Article §, Section, Title Case, ALL CAPS,
and legal preamble. Closes 0.70→0.95 precision gap vs naive.
```

3/5 — Citations
```
Every claim must carry a [file:page] marker. A second 7B LLM
audits the answer for ungrounded claims and surfaces them in the
UI as ⚠️ warnings.

The guard over-flags on 7B (treat as advisory). At 14B it
actually catches things.
```

4/5 — Operate it like a service
```
- Prometheus /metrics endpoint (firmbot_* collectors)
- Per-IP rate limit (10 RPS, 20 burst)
- Body size cap (413 before memory read)
- CORS allow-list (fail-closed default)
- Log redaction filter
- STRIDE threat model in SECURITY.md
```

5/5 — Try it
```
git clone https://github.com/Mine-FNL/firm-bot
cd firm-bot && pip install -e ".[dev,observability]"
firm-bot serve
→ http://localhost:8000
→ drop a PDF, ask a question, see the citation

MIT. PRs welcome.
```

Attach to tweet 5: `hero.png` and `demo.gif`.

## Channel 3 — Reddit

### r/LocalLLaMA (best fit)

**Title:**
```
firm-bot — local-first RAG for legal/audit, citations enforced, MIT
```

**Body:**
```
Sharing a project I've been building: firm-bot. Local-first
chatbot builder for professional services firms (legal, audit,
consultancy). Answers questions on your PDFs/EMLs/DOCX with
citations on every claim, no cloud calls.

The pitch: cloud RAG is fine for most use cases. It is NOT fine
when your corpus is privileged, regulated, or has to stay
air-gapped. firm-bot is the local-first option for those cases.

What's interesting:
- Structure-aware chunker (Article § / Section / Title Case /
  WHEREAS). On CUAD subset: 0.538 precision@k vs 0.462 naive
  sliding window.
- Citation-required prompt + 7B LLM-as-judge guard. 100%
  citation coverage in our e2e test; judge flags ungrounded
  claims.
- Hybrid retrieval (BM25 + dense via RRF, k=60). Cross-encoder
  reranker is opt-in; benchmark showed no lift on this fixture.
- RAGAS-style metrics (faithfulness, answer_relevancy, context
  precision, context recall) computed without the heavy ragas
  package.
- Prometheus /metrics + structured JSON logs + request-id
  propagation. Observability is opt-in: `pip install
  firm-bot[observability]`.
- Per-IP rate limit + body size cap + CORS allow-list (fail
  closed) + log redaction. STRIDE threat model in SECURITY.md.

Stack: FastAPI + Chroma + BM25 + sentence-transformers/fastembed
+ Ollama. Python 3.11+. MIT.

Self-host:
  git clone https://github.com/Mine-FNL/firm-bot
  cd firm-bot && pip install -e ".[dev,observability]"
  firm-bot serve

Demo: github.com/Mine-FNL/firm-bot/blob/main/docs/assets/marketing/demo.gif

Curious what the local-LLM crowd thinks — specifically the
citation-required pattern and whether the structure-aware chunker
generalises beyond contracts (we've only validated on legal
texts).
```

### r/Python

**Title:**
```
firm-bot — open-source local RAG for professional services, MIT
```

**Body:**
```
Sharing a Python project: firm-bot. Multi-tenant local-first
RAG chatbot builder. Drop your PDFs/EMLs/DOCX into a per-firm
folder, get a chat endpoint with citations on every claim.

Engineering highlights for the Python crowd:
- FastAPI + Starlette middleware (Observability + Security)
- Chroma + BM25 hybrid retrieval via Reciprocal Rank Fusion
- Structure-aware chunker with regex cascade (Article, Section,
  Title Case, WHEREAS)
- PDF/EML/DOCX extractors with OCR fallback (Tesseract)
- Per-firm filesystem isolation (separate Chroma collection +
  BM25 pickle per slug)
- Incremental indexing via SHA-256 manifest
- PII redaction (SSN/EIN/email/phone/credit card with Luhn
  validation/IBAN/IPv4)
- Prometheus /metrics via prometheus_client (opt-in extra)
- 129 tests pass, 74.47% coverage, ruff + mypy --strict clean

Try:
  pip install firm-bot
  firm-bot serve
  → http://localhost:8000

MIT licensed. github.com/Mine-FNL/firm-bot
```

### r/legaltech (smaller, high-signal)

**Title:**
```
Local-first RAG for legal — citations enforced, no cloud calls (open source)
```

**Body:**
```
Built something I wish existed when I was doing legal-tech work:
firm-bot. Multi-tenant local-first RAG for law firms and in-house
legal teams. Every claim carries a citation; nothing leaves your
machine.

Why local-first:
- Attorney-client privilege survives by chain of custody, not
  contract. Cloud vendors add a third party to your privilege
  analysis.
- GDPR / HIPAA / SOC2 — every cloud vendor is a subprocess or
  you. firm-bot removes the vendor.
- Audit trail ownership: your logs, your retention.

What it does:
- Per-firm folder of PDFs/EMLs/DOCX → chat endpoint
- Every answer cites [file:page]; guard LLM flags ungrounded
  claims
- Hybrid BM25 + dense retrieval, structure-aware chunker
- 0.538 precision@k on CUAD subset (10 contracts / 26
  questions) vs 0.462 for naive chunking

github.com/Mine-FNL/firm-bot — MIT, Python 3.11+, self-host
in 60s.

Happy to walk through the threat model if anyone wants to do
their own compliance review.
```

## Channel 4 — LinkedIn

**Post:**

```
We open-sourced firm-bot today.

It's a local-first RAG chatbot builder for professional services
firms — legal, audit, consultancy. The pitch is simple: if your
work product is privileged or regulated, you shouldn't have to
hand your corpus to a cloud vendor.

Three things I'm proud of:

1. The chunker. Contracts don't follow "Section 1, Section 2".
They have Article + Title Case headings, WHEREAS preambles,
indented exhibits, sectionless prose. Our structure-aware chunker
recognises all of that and closes the precision gap vs. naive
chunking (0.70 → 0.95 on a held-out contract corpus).

2. Citations are enforced, not aspirational. The system prompt
requires every claim to carry a [file:page] marker. A second LLM
audits the answer and flags ungrounded claims in the UI as
warnings. On our CUAD subset we hit 100% citation coverage.

3. It runs as a service you'd actually want to operate:
Prometheus /metrics, per-IP rate limit, body size cap, fail-closed
CORS, log redaction. STRIDE threat model in SECURITY.md.

Stack: FastAPI, Chroma, BM25, sentence-transformers, Ollama.
Python 3.11+. MIT.

github.com/Mine-FNL/firm-bot

If your firm has been wrestling with "vendor RAG doesn't satisfy
our compliance review" — this is the alternative. Happy to talk
through the threat model.
```

Attach: `hero.png` (1600x900).

## Channel 5 — Dev.to

**Title:**
```
Building firm-bot: a local-first RAG chatbot for legal & audit
```

**Outline:**

1. **The problem** — cloud RAG and the compliance gap
2. **Why local-first** — chain of custody, air-gap, audit trail
3. **The architecture** (use `architecture.png`) — six stages
4. **The hard parts:**
   - Structure-aware chunking (Article/Section/Title Case)
   - Citation-required prompts + LLM-as-judge guard
   - Hybrid retrieval (BM25 + dense + RRF)
5. **What we measured** — CUAD benchmark, 0.538 vs 0.462 naive
6. **Operating it** — Prometheus /metrics, rate limiting, threat model
7. **Try it** — `git clone … && firm-bot serve`
8. **What's next** — v0.2 roadmap (auth, multi-user, LoRA)

Length: ~1200 words. Code blocks for install + a query example.

Attach: `architecture.png`, `comparison.png`, `demo.gif`.

## Posting cadence (suggested)

- Day 0 (now): Show HN. Sit in the queue for ~2 hours, respond to comments.
- Day 0 evening: Twitter launch tweet + thread.
- Day 1: r/LocalLLaMA. Engage every comment for 24h.
- Day 2: r/Python.
- Day 3: r/legaltech + LinkedIn.
- Day 5: Dev.to article.
- Day 7+: cross-post to HackerNoon, InfoQ, Lobsters (if HN did well).

## Don't-do list

- **Don't** blast all channels simultaneously — diluted attention.
- **Don't** pretend this is bigger than it is. "v0.1, 10-contract
  benchmark, single-machine deployment" is the honest pitch.
- **Don't** ask for stars in the post body. Show the work; let the
  numbers speak.
- **Don't** respond to HN comments defensively. Acknowledge
  limitations out loud.

## Tracking

After the launch, watch:
- HN: rank, comment count, stars-from-HN
- GitHub: stars, forks, unique clones (`/repos/:owner/:repo/traffic/clones`)
- PyPI: download count (`pip install firm-bot`)
- Reddit: upvotes per subreddit, comment sentiment

The "stars" metric moves on the back of the e2e demo GIF landing
well on Twitter + the HN ranking. Don't over-optimise for any one
channel.
