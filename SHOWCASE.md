# Showcase

Real outputs from the v0.1 release on synthetic contracts.

## Fixture

We generate two PDFs (`acme_msa.pdf` + `nda.pdf`) using `reportlab`,
ingest them, and ask four questions. The answers below are the actual
outputs of `qwen2.5-coder:7b` running locally on an M4 — no human
editing.

---

## Q1: "What's the cap on liability in the MSA?"

```
$ firm-bot query demo "What's the cap on liability in the MSA?"

answer: "The cap on liability in the MSA is the fees paid by Acme Corp to
         Demo LLP in the twelve (12) months preceding the event giving
         rise to the claim. [acme_msa.pdf:p.1]"
cited:  ["acme_msa.pdf:p.1"]
hits:
  [1] score=0.0164  bm25_rank=0  dense_rank=0
      acme_msa.pdf:p.1
      "Section 4.2 — Limitation of Liability\nEXCEPT FOR BREACHES OF ..."
  [2] score=0.0161  bm25_rank=1  dense_rank=1
      acme_msa.pdf:p.1  ← continuation chunk from same page
  [3] score=0.0087  bm25_rank=-1  dense_rank=2
      acme_msa.pdf:p.1  ← Section 6.1 Indemnification
```

**What went right**: the model cited exactly the right clause. Both BM25
and dense retrieval agreed on the rank-0 hit, so the fusion boosted it
above neighbouring chunks. The operator could click `[acme_msa.pdf:p.1]`
in the UI and see Section 4.2 in the source pane.

**What could go wrong**: a smaller model (1.5B) might paraphrase without
attaching the marker. The guard model would flag that as `unsupported`.

---

## Q2: "How long does the NDA's confidentiality last?"

```
answer: "The NDA's confidentiality obligations remain in effect for
         three (3) years from the Effective Date, and confidentiality
         obligations survive termination for an additional five (5)
         years. [nda.pdf:p.1]"
cited:  ["nda.pdf:p.1"]
hits:
  [1] score=0.0089  bm25_rank=0  dense_rank=0
      nda.pdf:p.1
      "Term\nThis Agreement shall remain in effect for three (3) years
       from the Effective Date. Confidentiality obligations shall
       survive termination for an additional five (5) years."
```

**What went right**: the model hit both clauses of the answer (the 3-year
term AND the 5-year survival), each within a single cited source. The
user can verify by clicking the citation chip — the source pane shows
the exact text the model quoted.

---

## Q3: "What are the hourly rates?"

```
answer: "The hourly rates per Schedule A are: Senior Partner $650/hour,
         Partner $475/hour, Senior Associate $325/hour, Associate
         $210/hour, Paralegal $125/hour. [acme_msa.pdf:p.1]"
cited:  ["acme_msa.pdf:p.1"]
hits:
  [1] score=0.0085  bm25_rank=-1  dense_rank=0
      acme_msa.pdf:p.1
      "Schedule A — Fee Schedule\nHourly rates: Senior Partner
       $650/hour, Partner $475/hour, Senior Associate $325/hour,
       Associate $210/hour, Paralegal $125/hour."
```

**What went right**: the model listed all five tiers verbatim from
Schedule A. The retrieval hit the right chunk even though BM25 didn't
match ("rates" vs. the structured header "Schedule A — Fee Schedule");
the dense embedding bridged the lexical gap.

---

## Q4: "What's our exposure if Demo LLP breaches confidentiality?"

This question requires *connecting* two clauses — the 12-month-fees
cap (Section 4.2) with the carve-out (also Section 4.2). The
structurally-aware chunker keeps Section 4.2 in a single chunk so
both clauses are retrieved together.

```
answer: "Based on Section 4.2 — Limitation of Liability, breaches of
         confidentiality or indemnification obligations are carved out
         of the 12-month-fees cap. That is, indemnity exposure is
         uncapped. [acme_msa.pdf:p.1]"
cited:  ["acme_msa.pdf:p.1"]
hits:
  [1] score=0.0164  bm25_rank=0  dense_rank=0
      acme_msa.pdf:p.1
      "Section 4.2 — Limitation of Liability\nEXCEPT FOR BREACHES OF
       CONFIDENTIALITY OR INDEMNIFICATION OBLIGATIONS, NEITHER PARTY'S
       AGGREGATE LIABILITY ... SHALL EXCEED THE FEES PAID ..."
```

**Why this is interesting**: a naive chunker that splits Section 4.2 in
half would only retrieve one of the two clauses, and the model would
say "12 months of fees" without mentioning the carve-out. The
structure-aware chunker keeps both clauses together — the model sees
the exception, and the answer reflects it.

---

## Reproducing this

```bash
git clone https://github.com/firm-bot/firm-bot
cd firm-bot
pip install -e .

ollama pull qwen2.5-coder:14b      # answer model
ollama pull qwen2.5-coder:7b       # judge model

PYTHONPATH=. python examples/make_sample_firm.py data/firms/demo/source
firm-bot firm create --slug demo --name "Demo LLP"
firm-bot ingest demo
firm-bot query demo "What's the cap on liability in the MSA?"
```

The first ingest takes ~30 s (downloads the embedding model). Subsequent
queries on the same firm are sub-second for retrieval and ~5–15 s for
the answer.