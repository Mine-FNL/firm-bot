"""Answer layer: prompt construction + claim verification guard.

This is where firm-bot's core product claim lives: every answer must
cite a source for every factual claim. We enforce that in two layers:

1. **Prompt contract**: the system prompt demands bracketed source
   markers and a plain "I don't know" refusal when sources don't cover
   the question. The default ``answer_with_ollama`` function passes
   the top-K retrieved chunks as numbered sources with their citation
   markers baked in.

2. **Post-hoc guard**: ``verify_citations`` runs a cheap local LLM
   over the answer and asks it to flag claims that lack a citation or
   that contradict the cited source. Returns an annotated answer that
   the UI can render with "⚠️ ungrounded" badges.

The guard is deliberately tolerant — it does NOT block the user from
seeing what the model said. It annotates so a human can decide.
"""
from __future__ import annotations

from .guard import AnnotatedAnswer, verify_citations
from .prompt import build_messages, extract_cited_sources

__all__ = [
    "AnnotatedAnswer",
    "build_messages",
    "extract_cited_sources",
    "verify_citations",
]
