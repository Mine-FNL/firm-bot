"""Faithfulness evaluation harness.

Standalone module — runs from a JSON fixture (list of question + expected
sources + expected keywords) and reports per-case and aggregate scores.
This is the same logic ``firm-bot eval <slug> --fixture ...`` invokes;
we expose it as a module so CI can call it directly.

Fixture format
--------------

    {
      "cases": [
        {
          "question": "What's the cap on liability in the Acme MSA?",
          "expected_sources": ["acme_msa.pdf:p.12"],
          "expected_keywords": ["$5,000,000", "indemnification"]
        }
      ]
    }
"""
from __future__ import annotations

from .harness import run
from .ragas import (
    RagasScores,
    make_ollama_fn,
    score_all,
    score_answer_relevancy,
    score_context_precision,
    score_context_recall,
    score_faithfulness,
)

__all__ = [
    "RagasScores",
    "make_ollama_fn",
    "run",
    "score_all",
    "score_answer_relevancy",
    "score_context_precision",
    "score_context_recall",
    "score_faithfulness",
]
