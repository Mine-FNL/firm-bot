# firm-bot Litigation Pack

A self-contained, **opt-in** domain pack for civil-litigation adversarial-document
reading. Built on top of firm-bot v0.4.

## What it adds

| Component | Public name | Purpose |
|-----------|-------------|---------|
| Transcript extractor | `extract_transcript(path) -> list[Chunk]` | Reads deposition / hearing transcripts formatted as `[page:line] Q. … / A. …` lines. Each chunk carries `page` and `line` metadata. |
| Pleading extractor   | `extract_pleading(path) -> list[Chunk]`   | Reads complaints, motions, answers, briefs as numbered paragraphs. Each chunk carries `para_start` and `para_end` metadata. |
| Transcript chunker   | `chunk_transcript(text, lines_per_chunk=50)` | Q/A-aware splitter — never splits between a question and its answer. |
| Pleading chunker     | `chunk_pleading(text, paragraphs_per_chunk=10)` | Paragraph-aware splitter — never splits between numbered paragraphs. |
| System prompt suffix | `LITIGATION_SYSTEM_PROMPT_SUFFIX` | A prompt fragment appended to `FirmConfig.system_prompt` that primes the answer LLM for litigation work (citation conventions, witness-vs-exhibit handling, refusal pattern). |
| Sample corpus        | `sample_corpus_dir()` | 4 fully-fabricated, redacted documents: 1 complaint, 1 motion for summary judgment, 1 deposition excerpt, 1 court order. Total < 18 KB. |
| Dispatch hook        | `register()` / `unregister()` | Wire the pack's extractors into `firm_bot.ingest.common.dispatch` so `firm-bot ingest` picks up `TX_*` / `PL_*` / `EX_*` `.txt` files automatically. |

## What it does NOT change

- The base PDF / EML / DOCX / mbox extractors are untouched.
- The base chunker, retriever, answer builder, and citation guard are untouched.
- The pack does not edit `firm_bot/ingest/common.py` — `register()` does a runtime
  monkey-patch, not a code change.
- A firm that never calls `register()` sees exactly the same behaviour as
  firm-bot shipped without this subpackage.

## Filename conventions

The dispatch hook classifies files by filename prefix:

| Prefix | Class | Extractor |
|--------|-------|-----------|
| `TX_` | Transcript | `extract_transcript` |
| `PL_` | Pleading | `extract_pleading` |
| `EX_` | Exhibit (treated as pleading for chunking) | `extract_pleading` |
| (anything else) | — | Base dispatch handles it |

Suffix must be `.txt` for the pack extractors. PDFs continue to flow through
the base pypdf / OCR pipeline regardless of filename prefix.

## Enabling the pack

```python
from firm_bot.packs.litigation import register, LITIGATION_SYSTEM_PROMPT_SUFFIX
from firm_bot.config import FirmConfig

# 1. Wire extractors into the dispatch table (this process).
register()

# 2. Configure a firm for litigation work.
firm = FirmConfig(slug="acme-litigation", name="Acme Litigation Matters")
firm.system_prompt = LITIGATION_SYSTEM_PROMPT_SUFFIX
firm.save(firm_dir)

# Or, equivalently, do both in one call:
from firm_bot.packs.litigation import apply_to_firm
apply_to_firm(firm_dir)
```

After `register()`, the next call to `firm-bot ingest <firm-slug>` will see
`TX_*`, `PL_*`, `EX_*` `.txt` files in the firm's `source/` directory and route
them through the litigation extractors.

## Sample queries that showcase the pack

After ingesting the bundled sample corpus:

1. **Page:line transcript citation.** "What did Dr. Reyes conclude about the
   heat-treatment records?" — the answer should cite
   `[TX_deposition_acme_v_beta.txt:p.39:L18]` (or the closest page the
   retriever surfaces).

2. **Paragraph-numbered pleading citation.** "What is the operative complaint
   paragraph that alleges fraud?" — should cite
   `[PL_complaint_acme_v_beta.txt:¶15-16]` (the Facility and Certification
   Representations).

3. **Procedural posture.** "What did the court rule on the motion for
   summary judgment?" — should surface the `GRANTED IN PART and DENIED IN
   PART` disposition and cite `[PL_order_court.txt:p.<N>]`.

4. **Adversarial reading.** "Compare what Defendant argued in the MSJ with
   what the Court ruled on the economic-loss rule." — the answer should
   quote both the motion's argument and the order's holding side-by-side.

5. **Privilege handling.** "What is the firm's internal position on Daubert
   motions?" — should say "the sources do not address internal firm
   position; no internal memo on Daubert is in the corpus" (the pack's
   refusal pattern).

## Sample corpus (bundled)

All parties are placeholders (`ACME CORP`, `BETA CORP`); all dates and
attorney names are redacted. No real case names, no real party names, no
real attorney names. Each file is < 5 KB.

| File | Format | Pages |
|------|--------|-------|
| `PL_complaint_acme_v_beta.txt` | Complaint | single |
| `PL_motion_msj.txt`            | Motion for Summary Judgment | single |
| `TX_deposition_acme_v_beta.txt` | Deposition excerpt | 4 (pp. 38-41) |
| `PL_order_court.txt`           | Court order | single |

The deposition includes 16 page:line markers (`[38:1]` … `[41:16]`) and
24 Q/A pairs.

## Running the test suite

```bash
pytest tests/test_litigation_pack.py -v
```

8 tests cover: transcript extraction with page:line markers, pleading
extraction with paragraph numbers, chunker boundaries, system-prompt
content, sample-corpus integrity, pack registration round-trip, and the
no-regression guarantee that loading the pack does not break the base
ingestion path for PDF/EML/DOCX.

## Disabling the pack

```python
from firm_bot.packs.litigation import unregister
unregister()
```

This restores the original `firm_bot.ingest.common.dispatch`. The sample
corpus and the chunker/extractor/prompt functions remain importable for
tests and for callers that want to use them directly.

## Versioning

| Field | Value |
|-------|-------|
| `PACK_ID` | `litigation` |
| `PACK_VERSION` | `0.1.0` |
| `FIRM_BOT_MIN_VERSION` | `0.4.0` |
