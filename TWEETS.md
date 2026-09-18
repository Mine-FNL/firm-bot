# firm-bot — tweet threads (variants)

Three new thread variants that complement the launch thread already
in `MARKETING.md` (Channel 2). Each thread picks a single angle and
walks through it. Voice rules and the existing launch thread are in
`docs/marketing/DESIGN.md` and `MARKETING.md` respectively — read
those first if anything below looks off.

All assets referenced below live in `docs/assets/marketing/`.

---

## Thread A — Structure-aware chunker (technical deep-dive)

**Tweet 1/7 — Hook**
```
Naive chunking loses 7.6 points of precision on contracts.

We built a structure-aware chunker that recognises Article §, Section, Title Case, and WHEREAS preambles — and closed the gap.

Here's what it does, with the regex cascade.
```

[Visual: attach `architecture.png`]

**Tweet 2/7 — Why naive fails**
```
Contracts don't follow "Section 1, Section 2."

They have Article + Title Case headings (WHEREAS, RECITALS), indented exhibits, sectionless prose.

A 512-token sliding window slices mid-clause. Embedding captures half a sentence.
```

**Tweet 3/7 — Regex cascade**
```
Structure-aware chunker runs a regex cascade:

1. Article § (Article I, Article II, ...)
2. Section (Section 4.2)
3. Title Case (Limitation of Liability, Indemnification)
4. ALL CAPS preambles (WHEREAS, RECITALS, NOW THEREFORE)
5. Numbered clauses (1., 2., (a), (b))
```

**Tweet 4/7 — Priority order**
```
Cascade runs in priority order: section boundaries first, numbered clauses next, paragraph breaks, sentence breaks. 512-token window only fires if nothing else matches.

Natural unit of meaning survives into the chunk boundary.
```

**Tweet 5/7 — The number**
```
On the 10-contract CUAD subset:

naive sliding-window: 0.462 precision@k
structure-aware:      0.538 precision@k
+ reranker:           0.541 (within noise)

On Article + Title Case contracts (most US commercial agreements): 0.95 vs 0.70.
```

[Visual: attach `benchmark.png`]

**Tweet 6/7 — Tradeoffs**
```
Tradeoffs:
- chunk size varies more (200-1500 tokens)
- regex cascade adds ~3ms per page
- rule-based, not learned

If your corpus mixes emails with contracts, you'll want a hybrid pass.
```

**Tweet 7/7 — CTA**
```
If you've ever fought a chunker on legal text, this is for you.

Source + cascade spec: github.com/Mine-FNL/firm-bot

WHITEPAPER.md §3.3 has the full regex.

MIT. PRs welcome on edge cases.
```

[Visual: attach `architecture.png`]

---

## Thread B — Threat model / compliance

**Tweet 1/7 — Hook**
```
"It's open-source — why would I trust it?"

Because the threat model is in the repo. Because the security middleware is in the code. Because you can run your own pen-test.

Trust through transparency, not a vendor's brand.
```

[Visual: attach `comparison.png`]

**Tweet 2/7 — STRIDE: Spoofing + Tampering**
```
STRIDE is in SECURITY.md. Every category has specific firm-bot scenarios and mitigations:

Spoofing → per-IP rate limit, request-id propagation, slug validation
Tampering → SHA-256 manifest, citation-required prompts, LLM-as-judge
```

**Tweet 3/7 — STRIDE: Repudiation + Info disclosure**
```
Repudiation → structured JSON logs, UUIDv7 per request, audit fields (firm slug, query hash, citation count)

Info disclosure → per-firm filesystem isolation, PII redaction in logs, CORS allow-list (fail-closed)
```

**Tweet 4/7 — STRIDE: DoS + EoP**
```
DoS → per-IP rate limit (10 RPS / 20 burst), body cap (413 before read), request timeout, clean streaming disconnects

EoP → OAuth middleware skeleton (opt-in), per-firm OS-level permissions, no admin endpoints by default
```

**Tweet 5/7 — The "why trust" answer**
```
"If it's open-source, why would I trust it?" — concrete answer:

1. Read SECURITY.md. Threat model is published.
2. Run your own pen-test. Middleware is in the repo.
3. Audit deps. Lockfile is pinned.
4. Check CI: 129 tests, ruff, mypy --strict on every PR.
```

**Tweet 6/7 — Out of scope**
```
What firm-bot is NOT defending against (in SECURITY.md, explicitly):

- host OS compromise (defence-in-depth is on you)
- side-channel attacks on model inference (active research area)
- prompt injection via corpus content (open problem; not sanitised at ingest)
```

**Tweet 7/7 — CTA**
```
Trust through transparency, not a vendor's brand.

SECURITY.md → github.com/Mine-FNL/firm-bot/blob/main/SECURITY.md

v0.1. Honest about what it defends and what it doesn't.
```

[Visual: attach `why_local.png`]

---

## Thread C — Benchmarks & honest limitations

**Tweet 1/7 — Hook**
```
firm-bot v0.1, 10-contract CUAD subset:

0.538 precision@k vs 0.462 naive sliding-window.

7.6 points of precision, from structure-aware chunking.

Here's the full picture — including what we're honest about.
```

[Visual: attach `benchmark.png`]

**Tweet 2/7 — Benchmark scope**
```
CUAD subset: 10 contracts (MSA, NDA, SOW, license, employment, services, lease, supply, partnership, settlement) × 26 questions across limitation of liability, indemnification, governing law, term, IP, confidentiality, exclusivity, audit rights.
```

**Tweet 3/7 — RAGAS metrics**
```
RAGAS-style metrics, computed natively (no heavy ragas package):

faithfulness:      0.91
answer relevancy:  0.87
context precision: 0.78
context recall:    0.72

Caveat: ground truth comes from same model family. Real eval needs human annotation.
```

**Tweet 4/7 — Load benchmark**
```
Load benchmark: python3 -m eval.load --total 200 --concurrency 16

On 8-core CPU, no GPU, qwen2.5-coder:7b:

p50 latency: 1.8s
p95 latency: 4.2s
p99 latency: 6.1s
throughput:  4.2 queries/sec
```

**Tweet 5/7 — Honest limitations (1/2)**
```
Honest limitations:

- prompt injection not defended (open problem; mitigation is application-layer)
- model ceiling: 7B is 7B. Cloud vendors on GPT-4-class have a higher ceiling.
- benchmark coverage: CUAD subset, RAGAS subset, load. Not general legal Q&A, not adversarial.
```

**Tweet 6/7 — Honest limitations (2/2)**
```
More honest limitations:

- no multi-user auth in core. Opt-in OAuth skeleton; production needs reverse proxy or v0.2 middleware.
- chunker validated on legal texts only. Mixed corpuses need a hybrid pass.
- 129 tests, 74.47% coverage. Floor is CI-enforced, not aspirational.
```

**Tweet 7/7 — CTA**
```
v0.1. Real numbers. Real limits. Real source.

CUAD subset reproducible: python3 -m eval.cuad --chunker structure_aware

Load: python3 -m eval.load --total 200 --concurrency 16

github.com/Mine-FNL/firm-bot
```

[Visual: attach `benchmark.png`]

---

## Posting notes

- These three threads target different reader segments from the
  launch thread: Thread A is for engineers evaluating the chunker,
  Thread B is for compliance / security reviewers, Thread C is for
  benchmark-driven evaluators.
- Recommended cadence: post one per day after the launch tweet, in
  A → B → C order. Each can stand alone if the others aren't read.
- All threads link to the same repo. Asset suggestions are
  suggestions — the platform picks based on what's already attached
  to the parent tweet.