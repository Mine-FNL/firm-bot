# Email outreach

Three cold-outreach templates for the three audiences most likely to adopt firm-bot.
All templates are MIT-licensed and freely adaptable.

## Template A — Compliance / vendor-risk reviewer at a law firm or audit practice

**To:** {{ first_name }} (compliance, vendor risk, infosec)
**From:** founder@mine-fnl.example
**Subject:** Local-first RAG for privileged material — open source, no vendor on chain of custody

Hi {{ first_name }},

Quick context: I built [firm-bot](https://firm-bot.vercel.app), an MIT-licensed
local-first RAG chatbot builder for legal and audit firms. It runs entirely on
the firm's hardware — no cloud calls, no vendor on the chain of custody,
full audit log of every query (without storing the question or answer text).

The pitch for your vendor-risk review:

1. **No data leaves the network.** All inference, embedding, retrieval, and
   logging happens on the firm's own hardware. The only outbound traffic is
   the initial Ollama model pull.
2. **No third party in the privilege analysis.** The query path is
   localhost → local Ollama → local Chroma → response. The vendor never
   sees the corpus, the query, or the answer.
3. **Citation-required by default.** Every claim anchored to `[file:page]`;
   an LLM-as-judge flags ungrounded answers.
4. **STRIDE threat model published.** See `SECURITY.md` — every control
   mapped to a threat category.
5. **Per-firm audit log.** Append-only JSONL with configurable retention,
   SIEM-friendly (CSV/JSON/JSONL/Markdown export). Never logs the question
   or answer text — only their SHA-256 hashes and lengths.

If you're evaluating RAG tools for {{ firm_name }}'s privileged workload and
the answer to "where does the corpus go?" can't be "someone else's
infrastructure," [firm-bot](https://github.com/Mine-FNL/firm-bot) is worth a
30-minute pilot.

Happy to send a docker-compose that comes up on a single Linux box with a
sample contract corpus already ingested.

— {{ your_name }}

---

## Template B — Head of knowledge management / practice innovation at a mid-size firm

**To:** {{ first_name }} (KM lead, practice innovation, legal engineering)
**From:** founder@mine-fnl.example
**Subject:** A 3-command RAG setup for your firm's contracts — no cloud, no vendor

Hi {{ first_name }},

You probably know the Harvey / Spellbook pitch: "your firm's contracts, in
a chat interface, with citations." The pitch is great. The deployment model
is the problem — every cloud RAG product adds a vendor to the chain of
custody of the most sensitive work your firm does.

I built [firm-bot](https://github.com/Mine-FNL/firm-bot) as an MIT-licensed
alternative for firms that can't send privileged material to a third party.
It does the same thing — citation-required chat over your firm's documents —
but it runs on your hardware. No cloud calls. No vendor on the chain of
custody. No SOC 2 vendor review of someone else's infrastructure.

The full setup is three commands:

```
pip install --extra-index-url https://mine-fnl.github.io/firm-bot/simple/ firm-bot
firm-bot demo init
firm-bot serve
```

You get a working chat over a sample contract in under 5 minutes. To swap
in your firm's corpus, drop PDFs into `data/firms/<yourfirm>/source/` and
run `firm-bot ingest <yourfirm>`.

The differentiators:

- **Structure-aware chunker.** Recognises Article §, Section, Title Case,
  ALL CAPS, WHEREAS preambles. Sections stay intact under merge. We
  measured +1.7pp precision@k vs naive sliding-window on a 30-contract
  corpus.
- **Citation-required prompts.** Every claim anchored to `[file:page]`.
  An LLM-as-judge flags ungrounded answers.
- **Optional API key auth.** Bearer / X-API-Key headers. Exempts
  `/healthz` + `/metrics` for monitoring.
- **Per-firm audit log.** SIEM-friendly JSONL export.

Live preview at [firm-bot.vercel.app](https://firm-bot.vercel.app) — the
landing page has a real chat sample from the bundled corpus.

— {{ your_name }}

---

## Template C — IT / DevOps lead at a firm doing RAG evaluation

**To:** {{ first_name }} (IT, platform, devops)
**From:** founder@mine-fnl.example
**Subject:** One container, one model, one audit log — the RAG stack you actually want to deploy

Hi {{ first_name }},

Most RAG products you've evaluated look great in the demo and turn into a
deployment story involving vendor agreements, cloud egress reviews, and
"which model is fine for which tier of data." If you've been asked to find
something that doesn't add a vendor to the chain of custody, [firm-bot](https://github.com/Mine-FNL/firm-bot)
is worth a look.

What it is: a FastAPI + Chroma + Ollama stack that runs entirely on the
firm's hardware. The full thing comes up with:

```
docker compose up -d
```

That brings up firm-bot (FastAPI on :7860), Ollama (with auto-pull on
first boot — 1.5B model is ~1GB, 14B is ~9GB), and an audit log endpoint
that emits JSONL with retention you control.

What it does NOT do: call any cloud API during operation. The model
download is the only network egress.

Operational shape:

- `/healthz` and `/metrics` are first-class (Prometheus text exposition)
- `/v1/firms/{slug}/query` is the chat endpoint (with SSE streaming)
- `/v1/firms/{slug}/audit-log` returns the per-firm JSONL (json/csv/md/jsonl)
- Per-IP rate limit (10 RPS, 20 burst), request body cap (1 MB default)
- CORS allow-list (fail-closed when empty)
- Per-firm filesystem isolation — each firm lives in its own dir

Docker image is ~400 MB (Python 3.11 + firm-bot). No system services.
Single command to roll forward, single command to roll back.

The thing I want feedback on: the deploy story. If you've already got a
container platform (k8s, ECS, Nomad), firm-bot slots in cleanly. If you've
got nothing and need a single box that handles 5-10 concurrent users, the
16 GB / 8-core baseline works.

— {{ your_name }}

---

## Sequencing

Send Template A first to compliance (slowest decision). When they greenlight
a pilot, send B and C in parallel to the practice and IT leads. The
sequence lands in three different inboxes, each tuned to the language
their team uses.

For follow-up cadence:

- Day 3: "Did the demo render right on your end? Happy to do a 20-min walk-through."
- Day 7: "If compliance is the gate, here's the SECURITY.md doc — 5 pages, covers the STRIDE walk-through."
- Day 14: final touch — "Going to close the loop on my end. If timing isn't right, no problem — keep me on file."
