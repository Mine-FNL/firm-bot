# firm-bot marketing & design philosophy

The single source of truth for how firm-bot should look and sound
in public. Every asset — README, hero image, demo video, social
post — draws from this doc. When in doubt, this doc wins.

## One-sentence positioning

**firm-bot is the local-first RAG chatbot builder for professional
services firms that can't put client work product in someone else's
vector store.**

Everything else flows from this.

## Audience

Three readers, in priority order:

1. **In-house legal/IT/compliance** at a mid-to-large firm. They've
   already tried cloud RAG and hit a wall — DPA review, vendor risk
   assessment, air-gap requirement, or privilege concern. They want
   the cloud UX with on-prem control.
2. **OSS builders / platform engineers** who evaluate open-weight
   RAG options for themselves or their team. They know Ollama, they
   know Chroma, they want to see real numbers and clean code.
3. **Solo developers / fractional CTOs** at small firms building a
   client deliverable. They need it to "just work" on their laptop.

We optimise for reader 1. Reader 2 is the path to readers 1 and 3.
Reader 3 finds us because readers 1 and 2 ship it.

## Voice

**Quiet confidence.**

| We are | We are not |
|--------|------------|
| Technical, numbers-first | Marketing-speak, buzzwords |
| Honest about v0.1 limitations | Inflating claims past the data |
| Calm, present-tense prose | Excited, hype-laden |
| Direct ("Drop PDFs here. Ask. Cite.") | Soft ("Easy AI for your documents!") |
| Engineer-to-engineer | Sales-person-to-buyer |

Phrases we never use:
- "revolutionary", "game-changing", "next-gen", "AI-powered" (we
  are powered by a specific LLM — name it)
- "Easy", "simple", "just works" (we ship a real tool, not a toy)
- "Industry-leading" without a number to back it
- Emoji in headlines (acceptable in UI mockups only)

Phrases we lean into:
- "Citation-required" / "every claim" / "[file:page]"
- "Local-first" / "air-gappable" / "your data, your box"
- Real numbers ("0.538 precision@k vs 0.462", "129 tests",
  "74% coverage")
- Concrete tech stack (FastAPI + Chroma + Ollama — not "AI")

## Visual identity

### Palette

Dark mode default. The audience is engineers, operators, and
compliance folks — they live in dark terminals and dashboards.

| Role | Token | Hex | Use |
|------|-------|-----|-----|
| Background top    | slate-950  | `#0F172A` | gradient start |
| Background bottom | indigo-950 | `#1E1B5E` | gradient end |
| Panel            | slate-800  | `#1E293B` | cards, modals |
| Border           | slate-600  | `#475569` | dividers |
| Text             | slate-200  | `#F1F5F9` | body |
| Text dim         | slate-400  | `#94A3B8` | captions |
| Accent signal    | blue-400   | `#60A5FA` | primary highlight |
| Accent highlight | violet-400 | `#A78BFA` | secondary highlight |
| Success          | green-400  | `#4ADE80` | ✓ marks |
| Warning          | amber-400  | `#FBBF24` | ⚠ marks |
| Error            | red-500    | `#EF4444` | ✗ marks |

Never use a fourth accent. Two-accent rule: blue for "this is the
thing", violet for "this is special about the thing".

### Typography

- **Headlines**: bold sans-serif, ≥48px on hero, ≥32px in body
- **Body**: regular sans-serif, 20–24px on infographics
- **Code / file paths / queries**: monospace
- **Numbers in stats**: bold sans-serif, oversized (≥56px)
  when they are the headline; tabular nums in tables

We deliberately avoid Inter, Geist, and other "AI-startup" typefaces.
Helvetica (macOS) or DejaVu Sans (Linux) renders consistently
without bundling.

### Motifs

Three motifs recur across assets:

1. **The chat card** — a rounded-rectangle panel showing a question,
   answer, and citation marker. Always rendered the same way (accent
   border, monospace citation in violet).
2. **The pipeline** — six stages (Ingest → Chunk → Embed → Retrieve
   → Answer → Guard) flowing left-to-right. Used in architecture
   diagram, README header, demo video transitions.
3. **The CLI prompt** — `$ firm-bot serve` in monospace, shown
   whenever we depict "starting it up". This is the moment of
   empowerment, not the moment of complexity.

### Spacing & density

Generous. Never crowded. The hero image has 20%+ breathing room
around the headline. Tables have row padding ≥1.4× line height.

Code blocks get air around them. Headlines never butt up against
edges.

## Per-asset principles

Every asset must answer ONE question for the reader. If it answers
two, split it.

| Asset | Answers |
|-------|---------|
| Hero banner           | "What is firm-bot?" |
| Architecture diagram  | "How does it work?" |
| Comparison infographic| "Why local-first vs cloud?" |
| Why-local infographic | "Why does this matter for me?" |
| Benchmark chart       | "Is it any good?" |
| Demo GIF / video      | "What does it look like to use?" |
| Show HN body          | "Why should I care?" |
| Tweet thread          | "Should I click through?" |
| Reddit post           | "Is the engineering real?" |

## Story arc

Every asset tells the same five-act story:

1. **Pain** — privileged or regulated work product sits behind a
   compliance wall that cloud vendors can't satisfy.
2. **Constraint** — local-first, but you still want chat UX.
3. **Solution** — firm-bot's specific design choices (structure-aware
   chunker, citation-required prompt, LLM-as-judge, hybrid retrieval).
4. **Proof** — real numbers from real benchmarks (CUAD subset,
   0.538 precision@k).
5. **Invitation** — `git clone … && firm-bot serve`. Or
   `pip install firm-bot`. Or `gh repo star`.

When an asset skips a beat, the reader has to fill in the gap
themselves. Most won't.

## Don't-do list

- Don't ship a marketing asset that doesn't cite a number.
- Don't use the word "AI" without a qualifier (which model, which
  size, which task).
- Don't screenshot an idealized UI and pretend it's the product.
  Either show the real product or render a clearly-marked mockup.
- Don't use "secure" without specifying what kind (TLS-in-transit?
  at-rest encryption? sandboxed inference?).
- Don't compare to a vendor without a specific dimension (cost,
  latency, citations, tenancy).
- Don't promise a feature in marketing copy that isn't in `main`
  with tests.

## Consistency checklist (use before publishing)

- [ ] Palette matches this doc
- [ ] Two-accent rule (blue + violet only)
- [ ] No emoji in headlines
- [ ] At least one real number visible
- [ ] One idea only (split if needed)
- [ ] Renders correctly at thumbnail size (test by viewing at 200px)
- [ ] Works in light and dark contexts (assets are dark-on-dark)

## When the philosophy changes

Don't. If you need to evolve the palette or add a third accent,
update this doc FIRST, then update the assets, then ship. Mixing
old and new visual identity in the same campaign is worse than
either alone.
