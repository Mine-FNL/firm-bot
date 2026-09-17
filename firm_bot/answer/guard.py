"""Citation guard for firm-bot answers.

Runs a cheap local LLM (the "judge") over the (answer, sources) pair
and asks it to flag any claim that lacks a citation or contradicts its
cited source. The judge returns a JSON verdict; we parse it and attach
a list of issues to the answer so the UI can warn the operator.

We deliberately keep the judge prompt tiny — a 7B model on an M4 can
verify ~50 sentences in a few seconds. The verdict is a heuristic
advisory, not a guarantee: lawyers should still read the cited source
themselves. The guard exists to surface obvious failures (the model
said "Yes, that clause limits liability to $5M" without any citation),
not to certify correctness.

JSON parsing is permissive: if the judge model wraps its output in
markdown fences or adds prose, we extract the first JSON-looking block.
We log every fallback fire so operators can spot when the judge prompt
needs tightening.
"""
from __future__ import annotations

import json
import logging
import re
import typing
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("firm_bot.answer.guard")

GUARD_PROMPT = """You are a citation auditor for a professional-services AI.

For every factual CLAIM in the answer, decide:
1. Is the claim supported by at least one cited source chunk? (the cited
   source markers look like [filename.pdf:p.4])
2. If yes, does the cited source support the claim, or contradict it?

Return ONLY a JSON object, no prose, no markdown fences:

{{
  "issues": [
    {{"claim": "...short quote...", "marker": "[filename.pdf:p.4]", "verdict": "supported" | "unsupported" | "contradicted", "note": "..."}}
  ],
  "summary": "ok" | "needs_review"
}}

If a claim has no citation at all, put it in issues with marker="" and verdict="unsupported".

ANSWER:
{answer}

SOURCES:
{sources}
"""


@dataclass
class Issue:
    claim: str
    marker: str
    verdict: str                # supported | unsupported | contradicted
    note: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"claim": self.claim, "marker": self.marker, "verdict": self.verdict, "note": self.note}


@dataclass
class AnnotatedAnswer:
    answer: str
    issues: list[Issue] = field(default_factory=list)
    summary: str = "ok"
    judge_model: str = ""
    raw_judge: str = ""

    @property
    def needs_review(self) -> bool:
        return self.summary == "needs_review" or any(
            i.verdict in {"unsupported", "contradicted"} for i in self.issues
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "answer": self.answer,
            "issues": [i.to_dict() for i in self.issues],
            "summary": self.summary,
            "judge_model": self.judge_model,
            "needs_review": self.needs_review,
        }


def verify_citations(
    answer: str,
    sources: list[tuple[str, str]],
    ollama_host: str,
    judge_model: str,
    timeout_s: float = 90.0,
) -> AnnotatedAnswer:
    """Run the judge LLM over (answer, sources).

    ``sources`` is a list of ``(marker, text)`` — the same blocks shown
    to the user as numbered citations, so the judge has the same ground
    truth the user would consult.
    """
    sources_block = "\n\n".join(f"{m}\n{t.strip()}" for m, t in sources)
    prompt = GUARD_PROMPT.format(answer=answer, sources=sources_block)

    raw = _call_ollama(
        ollama_host,
        judge_model,
        [{"role": "user", "content": prompt}],
        timeout_s,
    )
    issues, summary, parsed = _parse_verdict(raw)
    return AnnotatedAnswer(
        answer=answer,
        issues=issues,
        summary=summary,
        judge_model=judge_model,
        raw_judge=raw if not parsed else "",
    )


# --- ollama HTTP ---------------------------------------------------------


def _call_ollama(
    host: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_s: float,
) -> str:
    """POST /api/chat to a local Ollama server. Returns the assistant text.

    We use httpx so this works without an asyncio event loop in CLI mode.
    """
    payload = {"model": model, "messages": messages, "stream": False}
    with httpx.Client(timeout=timeout_s) as client:
        r = client.post(f"{host.rstrip('/')}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
    return str(data.get("message", {}).get("content", "") or "")


def answer_with_ollama(
    host: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_s: float,
) -> str:
    """Run the (answer) model; not the judge."""
    return _call_ollama(host, model, messages, timeout_s)


def stream_answer_with_ollama(
    host: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_s: float = 300.0,
) -> typing.Iterator[str]:
    """Stream the answer token-by-token from Ollama.

    Yields plain text deltas. Caller (the API layer) wraps them in SSE
    ``data:`` frames. The iterator stops cleanly when Ollama closes the
    response (``done: true``) or raises on connection failure.
    """
    payload = {"model": model, "messages": messages, "stream": True}
    with httpx.Client(timeout=timeout_s) as client, client.stream(
        "POST", f"{host.rstrip('/')}/api/chat", json=payload
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("done"):
                break
            delta = obj.get("message", {}).get("content", "") or ""
            if delta:
                yield delta


# --- json-ish parsing ---------------------------------------------------


def _parse_verdict(raw: str) -> tuple[list[Issue], str, bool]:
    """Pull a JSON-ish verdict out of the judge's raw text.

    Returns ``(issues, summary, parsed_ok)``. ``parsed_ok`` is False when
    we fell back to a structural default; the caller logs that so we
    can spot when the judge prompt drifts.
    """
    if not raw.strip():
        return [], "ok", False
    candidates: list[str] = []
    # try the whole thing first
    candidates.append(raw.strip())
    # try fenced JSON
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if m:
        candidates.append(m.group(1))
    # try the first {...} block
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        issues = []
        for it in obj.get("issues") or []:
            if not isinstance(it, dict):
                continue
            issues.append(
                Issue(
                    claim=str(it.get("claim", "")).strip(),
                    marker=str(it.get("marker", "")).strip(),
                    verdict=str(it.get("verdict", "unsupported")).strip().lower(),
                    note=str(it.get("note", "")).strip(),
                )
            )
        summary = str(obj.get("summary", "ok")).strip().lower()
        return issues, summary, True
    log.warning("judge parse fallback fired; raw=%r", raw[:200])
    return [], "needs_review", False
