"""Lightweight prompt-injection pre-pass on retrieved chunks.

This is NOT a real defence — it catches obvious patterns and surfaces
them as warnings in the response. Real defence is the instruction-defence
suffix in ``prompt.py`` plus this module's pre-filter.

Patterns flagged (case-insensitive substring match):

  - "ignore previous instructions"
  - "ignore all previous"
  - "you are now"
  - "system:" / "assistant:" role hijacks
  - "disregard the above"
  - "reveal the prompt"
  - "reveal the user's question"
  - "reveal your system prompt"
  - "print the conversation"
  - "act as"
  - "your new instructions"

False positives are expected (a contract legitimately saying "you are
now authorised to..." would trip this). The downstream guard model + the
instruction-defence suffix handle the cases this filter misses; this
filter's job is to surface suspicious chunks for human review via the
``prompt_injection_suspected`` flag on the response.

Configuration:

  - ``FIRM_BOT_INJECTION_FILTER=0`` disables the pre-pass.
  - Default: enabled.

The filter does NOT refuse the request. It annotates the response with
a counter and a warning string so operators can investigate.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

# Substring patterns. Case-insensitive. Each pattern is a compiled
# regex; ``re.IGNORECASE`` is set on every compile.
#
# Note on regex structure: alternations are ordered longest-first in
# each group (``system prompt`` before ``prompt``) so the regex engine
# matches the more specific alternative first. Without that ordering,
# "reveal system prompt" fails because "prompt" tries to match at
# the start of "system prompt" and gives up.
_PATTERNS: tuple[str, ...] = (
    r"ignore (?:all |the )?previous instructions?",
    r"ignore (?:the )?above",
    r"disregard (?:the )?(?:above|previous)",
    r"you are now",
    r"from now on you (?:are|will|must)",
    r"system:\s*you",
    r"assistant:\s*you",
    r"reveal (?:the |your |my )?(?:system prompt|prompt|user(?:'s)? question)",
    r"print (?:the )?(?:conversation|prompt|context)",
    r"act as",
    r"new instructions?:",
    r"override (?:the )?(?:system|previous)",
    r"forget (?:everything|all) (?:above|before)",
    r"do not (?:follow|obey) (?:the )?(?:user|system)",
    r"end of (?:prompt|system)",
)

_COMPILED: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _PATTERNS
)


def scan_text(text: str) -> list[str]:
    """Return a list of patterns that matched in ``text``.

    Empty list = no injection patterns detected. The caller decides
    what to do with a non-empty list (annotate the response, refuse
    the query, fire a metric, etc.).

    The first matching pattern is enough to flag — we don't return
    every match, just distinct patterns. Order is stable.
    """
    if not text:
        return []
    matches: list[str] = []
    for i, pat in enumerate(_COMPILED):
        if pat.search(text):
            matches.append(_PATTERNS[i])
    return matches


def scan_hits(hits: Iterable[object]) -> tuple[int, list[str]]:
    """Scan retrieval hits for injection patterns.

    Returns (suspicious_chunk_count, patterns_found). Caller is
    expected to add the count to the audit-log record and surface
    the patterns as a ``prompt_injection_suspected`` field on the
    response.

    ``hits`` are duck-typed (we only read ``.text``) so this works
    with ``list[RetrievalHit]``, ``list[_FakeHit]`` (in tests), or
    any other iterable whose items have a ``.text`` attribute.
    ``Iterable[object]`` (covariant) is used so callers don't need
    to upcast when passing typed lists.
    """
    total = 0
    patterns_seen: set[str] = set()
    for h in hits:
        text = getattr(h, "text", "")
        if not text:
            continue
        matches = scan_text(text)
        if matches:
            total += 1
            patterns_seen.update(matches)
    return total, sorted(patterns_seen)
