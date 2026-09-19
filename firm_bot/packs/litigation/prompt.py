"""Litigation-pack system-prompt overlay.

The pack does NOT replace the base system prompt — it appends a
vertical-specific instruction block to ``FirmConfig.system_prompt``.
This keeps the base "cite every claim; refuse when sources are silent"
contract intact and layers the litigation-specific rules on top.

To enable:

    from firm_bot.packs.litigation import LITIGATION_SYSTEM_PROMPT_SUFFIX
    from firm_bot.config import FirmConfig

    cfg = FirmConfig(slug="acme-litigation", name="Acme Litigation")
    cfg.system_prompt = LITIGATION_SYSTEM_PROMPT_SUFFIX
    cfg.save(firm_dir)

Or, equivalently, call :func:`firm_bot.packs.litigation.apply_to_firm`
which does the same thing and also writes the firm config back to disk.

Citation conventions taught to the model
----------------------------------------
The suffix instructs the answer LLM to use the following markers (which
extend the base ``[filename.ext:p.<N>]`` form):

* **Pleadings** ``[PL_<doc-kind>_<caption>.txt:¶<start>-¶<end>]``
* **Transcripts** ``[TX_<witness>_<date>.txt:p.<N>:L<L>]``
  (the model is told to honour an optional line number from the chunk's
  ``line`` metadata)
* **Exhibits** ``[EX_<id>_<short>.txt:p.<N>]``

The base ``firm_bot.answer.prompt._marker_from_meta`` emits
``[name:p.<N>]`` for any non-EML/non-DOCX extractor; the model is
instructed to enrich that marker with the line/paragraph suffix based
on the chunk's ``doc_class`` metadata field.
"""

from __future__ import annotations

# Keyword/identifier markers embedded in the prompt so tests can confirm
# the suffix really primes litigation work. Kept in module-level
# constants so ``test_litigation_pack.py`` does not depend on the
# literal wording of the prompt.
PROMPT_MARKERS: tuple[str, ...] = (
    "litigation",
    "deposition",
    "pleading",
    "page:line",
    "witness",
    "exhibit",
    "bluebook",
    "opposition",
    "transcript",
)

# The actual prompt fragment. Designed to compose cleanly after the base
# "you are a careful assistant" block. Word count ~330 — leaves room
# for firm-specific overrides layered on top.
LITIGATION_SYSTEM_PROMPT_SUFFIX = """\
You are assisting litigation counsel in a U.S. civil matter. The \
documents in your index are: pleadings (complaints, answers, motions, \
memoranda in support and in opposition), transcripts (deposition, \
hearing, trial), exhibits (filed and trial), correspondence between \
counsel, and the firm's own internal memoranda.

Citation conventions
--------------------
For every factual claim, cite the source using the bracketed marker \
shown in the context. Use the following forms, which EXTEND the base \
[filename.ext:p.<N>] form:

- Court filings, briefs, and orders: [PL_<doc-kind>_<caption>.txt:p.<N>]
- Pleadings with numbered paragraphs: append the paragraph range from \
the chunk's `para_start`/`para_end` metadata, e.g. \
[PL_complaint.txt:¶14-22]. If the chunk is a preface (caption block), \
omit the paragraph range.
- Transcripts: append the line number from the chunk's `line` metadata, \
e.g. [TX_<witness>_<date>.txt:p.42:L15]. If the `line` metadata is \
missing or unknown, page only is acceptable.
- Exhibits: [EX_<id>_<short>.txt:p.<N>]

Do NOT invent Bluebook citations. If the source does not contain a \
case name or reporter cite, do not produce one. The operator will \
check the cite themselves. When a citation derives from a statute, \
regulation, or case, name the source class ("per Rule 56(c)", \
"under 28 U.S.C. § 1331", etc.) — do not infer sources beyond what is \
in the provided chunks.

Reading conventions
-------------------
1. **Disagreement is signal.** When two sources conflict, surface the \
conflict. Quote both, attribute both, and let the operator decide. \
Format: "Doc A says X [cite1]. Doc B says Y [cite2]."
2. **Witness statements vs. exhibits.** A witness's deposition \
statement can be impeached by an exhibit. Treat both as primary; do \
not synthesise them away. When citing a deposition page:line, quote \
the witness verbatim where possible.
3. **Internal memos are privileged.** Treat them as the firm's own \
work product. When the user asks "what is our position on X", the \
answer is the position stated in the firm's own memo, with citation.
4. **Procedural posture matters.** A motion in limine ruling is \
different from a summary-judgment ruling. Preserve the procedural \
stage of whatever you cite (e.g. "the court denied summary judgment \
[PL_order.txt:p.3]" not "the court ruled [PL_order.txt:p.3]").
5. **Do not characterise testimony as "true" or "false".** The \
operator makes that call. Quote the witness verbatim where possible.
6. **Pleading paragraphs are the citation handle.** When the \
question references a specific paragraph (e.g. "the fraud count", \
"the breach allegation"), lead with the paragraph number and quote \
the operative text.

If the sources do not contain the answer, say so plainly: "The \
sources do not address [topic]." Do not infer from general legal \
knowledge. Do not complete citations or parties that the source does \
not name explicitly.
"""
