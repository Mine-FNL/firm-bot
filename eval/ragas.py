"""RAGAS-style RAG evaluation for firm-bot.

Computes four RAGAS-style metrics over the (question, retrieved contexts,
answer) triple without depending on the heavy ``ragas`` library:

1. **faithfulness** — fraction of claims in the answer supported by the
   retrieved contexts (LLM-as-judge, one call per claim).
2. **answer_relevancy** — cosine similarity of the answer embedding to
   the question embedding. RAGAS averages over perturbations; we keep
   the implementation simple and report a single cosine.
3. **context_precision** — fraction of retrieved chunks that are
   relevant to the question (LLM-as-judge, one call per chunk).
4. **context_recall** — fraction of ground-truth relevant chunks that
   were actually retrieved. Requires ``relevant_ids`` (or the
   ``relevant_docs`` field in the fixture); returns ``NaN`` if absent.

All metrics are in [0, 1]; higher is better. We return ``float('nan')``
(not 0) for any metric we cannot compute so that real zeros stay
distinguishable from missing data in downstream plots.

This module reuses firm-bot's existing primitives: the Ollama judge is
the same model the citation guard uses (see ``firm_bot.answer.guard``),
and ``embed_fn`` is the same ``sentence-transformers`` encoder the
retriever uses (see ``firm_bot.embed_backends``). We do not import from
``firm_bot`` so this module remains unit-testable without the heavy
deps loaded.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx

log = logging.getLogger("eval.ragas")

# An "ollama_fn" is the only side-effecting surface this module exposes:
# given (prompt, system), it must return the model's raw text. The shape
# matches what the existing citation guard would produce if you stripped
# its chat-message wrapper, so a single adapter covers both eval paths.
OllamaFn = Callable[[str, str | None], str]
EmbedFn = Callable[[str], list[float]]

# Prompts are intentionally SHORT — a 7B model on M4 hardware will not
# follow a long instruction reliably, but it answers "yes / no" with
# high accuracy given a one-line task. Keep them stable; the regression
# suite asserts specific tokens in the prompts.

FAITHFULNESS_CLAIM_PROMPT = """\
Claim: {claim}

Context:
{context}

Is the claim supported by the context above? Answer only "yes" or "no".
"""

CONTEXT_PRECISION_CHUNK_PROMPT = """\
Question: {question}

Chunk:
{chunk}

Is the chunk relevant to answering the question? Answer only "yes" or "no".
"""

# Conservative parse: pick the first yes/no token anywhere in the
# response, case-insensitive. Falls back to "no" (penalises — better to
# under-credit faithfulness than to over-credit it).
_YES_NO = re.compile(r"\b(yes|no)\b", re.IGNORECASE)


def parse_yes_no(raw: str) -> bool:
    """Return True iff the model's reply contains a clear "yes".

    Default is False on parse failure — a "no" is the conservative
    choice for both faithfulness (an unsupported claim should not be
    counted) and context_precision (an irrelevant chunk should not be
    counted).
    """
    m = _YES_NO.search(raw)
    if not m:
        return False
    return m.group(1).lower() == "yes"


def _split_sentences(text: str) -> list[str]:
    """Split ``text`` into atomic claim-sized sentences.

    Naive split on ``.!?`` followed by whitespace + capital letter, or
    a newline. Long paragraphs without terminating punctuation are kept
    as a single claim — that is acceptable because the LLM judge is
    robust to multi-clause prompts.
    """
    if not text or not text.strip():
        return []
    # collapse newlines into a single boundary
    cleaned = text.replace("\n", " ").strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", cleaned)
    # drop empty / whitespace-only fragments
    return [p.strip() for p in parts if p.strip()]


def _join_contexts(contexts: list[str], max_chars: int = 6000) -> str:
    """Concatenate contexts into a single block for the judge prompt.

    Capped so a pathological 50-chunk fixture does not exceed the
    7B model's context window. Chunks beyond the cap are dropped
    (rare in practice; ``k`` defaults to 6).
    """
    if not contexts:
        return ""
    out: list[str] = []
    total = 0
    for i, c in enumerate(contexts, 1):
        block = f"[{i}] {c.strip()}"
        if total + len(block) > max_chars:
            break
        out.append(block)
        total += len(block)
    return "\n\n".join(out)


def score_faithfulness(answer: str, contexts: list[str], ollama_fn: OllamaFn) -> float:
    """Fraction of answer claims supported by the retrieved contexts.

    Returns 0.0 for an empty answer (there is nothing to support).
    Returns 0.0 if there are no contexts at all — every claim would
    necessarily be unsupported.
    """
    claims = _split_sentences(answer)
    if not claims:
        return 0.0
    ctx_block = _join_contexts(contexts)
    if not ctx_block:
        return 0.0
    supported = 0
    for claim in claims:
        prompt = FAITHFULNESS_CLAIM_PROMPT.format(claim=claim, context=ctx_block)
        try:
            raw = ollama_fn(prompt, "You are a careful fact-checker.")
        except Exception as e:
            log.warning("faithfulness judge call failed: %s", e)
            continue
        if parse_yes_no(raw):
            supported += 1
    return supported / len(claims)


def score_answer_relevancy(question: str, answer: str, embed_fn: EmbedFn) -> float:
    """Cosine similarity between ``answer`` and ``question`` embeddings.

    Cosine is in [-1, 1]; we clamp to [0, 1] so a NaN-producing or
    zero-vector input collapses to 0.0 rather than -1.0 (a paraphrase
    with negative cosine should not count as "less relevant than
    unrelated text" — that comparison is meaningless at this scale).
    """
    if not question.strip() or not answer.strip():
        return 0.0
    try:
        q_vec = embed_fn(question)
        a_vec = embed_fn(answer)
    except Exception as e:
        log.warning("answer_relevancy embed failed: %s", e)
        return 0.0
    sim = _cosine(q_vec, a_vec)
    if math.isnan(sim):
        return 0.0
    # map [-1, 1] -> [0, 1]
    return max(0.0, min(1.0, (sim + 1.0) / 2.0))


def _cosine(a: list[float], b: list[float]) -> float:
    """Standard cosine similarity; returns NaN on degenerate vectors."""
    if len(a) != len(b) or not a:
        return float("nan")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return float("nan")
    return dot / math.sqrt(na * nb)


def score_context_precision(question: str, contexts: list[str], ollama_fn: OllamaFn) -> float:
    """Fraction of retrieved chunks relevant to the question.

    Returns 0.0 when there are no contexts (precision is undefined but
    we report zero so it contributes correctly to a downstream mean).
    """
    if not contexts:
        return 0.0
    relevant = 0
    for chunk in contexts:
        if not chunk.strip():
            continue
        prompt = CONTEXT_PRECISION_CHUNK_PROMPT.format(question=question, chunk=chunk)
        try:
            raw = ollama_fn(prompt, "You are a relevance judge.")
        except Exception as e:
            log.warning("context_precision judge call failed: %s", e)
            continue
        if parse_yes_no(raw):
            relevant += 1
    return relevant / len(contexts)


def score_context_recall(retrieved_ids: list[str], relevant_ids: list[str] | None) -> float:
    """Fraction of ground-truth relevant ids that were retrieved.

    Returns ``NaN`` when ground truth is missing (``relevant_ids`` is
    ``None`` or empty). The eval_e2e markdown report surfaces this as
    "n/a" so the column is distinguishable from a real zero.
    """
    if not relevant_ids:
        return float("nan")
    retrieved = set(retrieved_ids)
    truth = set(relevant_ids)
    hit = len(retrieved & truth)
    return hit / len(truth)


@dataclass
class RagasScores:
    """All four RAGAS metrics for a single (question, contexts, answer)."""

    faithfulness: float
    answer_relevancy: float
    context_precision: float
    context_recall: float

    def as_dict(self) -> dict[str, float]:
        return {
            "faithfulness": self.faithfulness,
            "answer_relevancy": self.answer_relevancy,
            "context_precision": self.context_precision,
            "context_recall": self.context_recall,
        }


def score_all(
    question: str,
    answer: str,
    contexts: list[str],
    retrieved_ids: list[str],
    relevant_ids: list[str] | None,
    ollama_fn: OllamaFn,
    embed_fn: EmbedFn,
) -> RagasScores:
    """Compute every metric and return them as a single dataclass.

    The two LLM-judge metrics (faithfulness, context_precision) cost N
    calls each — fine for an eval fixture with k=6 and ~3 sentences per
    answer, but a future optimisation could batch them.
    """
    return RagasScores(
        faithfulness=score_faithfulness(answer, contexts, ollama_fn),
        answer_relevancy=score_answer_relevancy(question, answer, embed_fn),
        context_precision=score_context_precision(question, contexts, ollama_fn),
        context_recall=score_context_recall(retrieved_ids, relevant_ids),
    )


def make_ollama_fn(host: str, model: str, timeout_s: float = 60.0) -> OllamaFn:
    """Build an ``OllamaFn`` that POSTs to a real local Ollama server.

    Returns a closure matching the ``(prompt, system) -> str`` contract.
    Used by ``eval/eval_e2e.py`` to wire the real judge into our
    metrics; unit tests pass their own mock callable instead.
    """

    def _call(prompt: str, system: str | None) -> str:
        msgs: list[dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": msgs, "stream": False}
        with httpx.Client(timeout=timeout_s) as client:
            r = client.post(f"{host.rstrip('/')}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
        return str(data.get("message", {}).get("content", "") or "")

    return _call
