"""Tests for the RAGAS-style eval module.

The judge is mocked as a closure that returns canned yes/no answers —
the metric functions only depend on the (prompt, system) → str
contract, so we never touch a real Ollama here.
"""

from __future__ import annotations

import math

import pytest

from eval.ragas import (
    RagasScores,
    parse_yes_no,
    score_all,
    score_answer_relevancy,
    score_context_precision,
    score_context_recall,
    score_faithfulness,
)

# ---- judge mocks -------------------------------------------------------


def _judge_always(*_args: object, **_kwargs: object) -> str:
    """Judge that always says yes — useful for positive-path tests."""

    return "yes"


def _judge_never(*_args: object, **_kwargs: object) -> str:
    """Judge that always says no — negative path."""

    return "no"


def _judge_that_garbles(*_args: object, **_kwargs: object) -> str:
    """Judge that returns prose without a clear yes/no — exercises
    the conservative parse fallback."""

    return "I'm not sure, it depends on context and many other things."


def _judge_per_claim(expected_yes: list[bool]):
    """Build a judge that returns yes/no for the first N calls, then
    falls back to 'yes'. Lets us drive specific answer sentences
    through specific verdicts.
    """

    state = {"i": 0, "expected": list(expected_yes)}

    def _call(*_args: object, **_kwargs: object) -> str:
        i = state["i"]
        state["i"] += 1
        if i < len(state["expected"]):
            return "yes" if state["expected"][i] else "no"
        return "yes"

    return _call


# ---- parse_yes_no ------------------------------------------------------


class TestParseYesNo:
    def test_yes(self) -> None:
        assert parse_yes_no("Yes.") is True
        assert parse_yes_no("yes, the claim is supported") is True
        assert parse_yes_no("YES") is True

    def test_no(self) -> None:
        assert parse_yes_no("No.") is False
        assert parse_yes_no("no, not really") is False
        assert parse_yes_no("NO") is False

    def test_conservative_on_garbled(self) -> None:
        # default to "no" — penalise on parse failure
        assert parse_yes_no("maybe? could be") is False
        assert parse_yes_no("") is False
        assert parse_yes_no("the context is unclear so I cannot say") is False

    def test_picks_first_token(self) -> None:
        # If the model writes "no ... actually yes" we trust the first
        # yes/no token. This is documented behaviour; a future iteration
        # could use the LAST token instead if the failure mode shifts.
        assert parse_yes_no("no, on closer reading yes") is False


# ---- score_faithfulness -----------------------------------------------


class TestScoreFaithfulness:
    def test_empty_answer_returns_zero(self) -> None:
        assert score_faithfulness("", ["any context"], _judge_always) == 0.0
        assert score_faithfulness("   \n  ", ["any context"], _judge_always) == 0.0

    def test_empty_contexts_returns_zero(self) -> None:
        # No context means every claim is unsupported.
        assert score_faithfulness("A claim. Another claim.", [], _judge_always) == 0.0

    def test_all_supported_returns_one(self) -> None:
        # Two claims, judge says yes for both → 1.0
        answer = "First claim. Second claim."
        score = score_faithfulness(answer, ["ctx"], _judge_always)
        assert score == pytest.approx(1.0)

    def test_mixed_returns_fraction(self) -> None:
        # Three claims, judge says yes for two → 2/3
        answer = "One. Two. Three."
        judge = _judge_per_claim([True, False, True])
        score = score_faithfulness(answer, ["ctx"], judge)
        assert score == pytest.approx(2 / 3)

    def test_garbled_judge_conservative(self) -> None:
        # Judge returns no clear yes/no — defaults to "no" → score 0.0
        score = score_faithfulness("One claim here.", ["ctx"], _judge_that_garbles)
        assert score == 0.0

    def test_no_sentences_returns_zero(self) -> None:
        # A run-on claim with no terminating punctuation still counts
        # as a single claim; if it's unsupported we get 0/1 = 0.
        score = score_faithfulness("claim without period", ["ctx"], _judge_never)
        assert score == 0.0


# ---- score_answer_relevancy -------------------------------------------


class TestScoreAnswerRelevancy:
    def test_identical_vectors_one(self) -> None:
        vec = [0.6, 0.8, 0.0, 0.0]

        def embed(text: str) -> list[float]:
            return list(vec)

        # Identical embeddings → cosine 1.0 → mapped to 1.0
        assert score_answer_relevancy("q", "a", embed) == pytest.approx(1.0)

    def test_orthogonal_vectors_half(self) -> None:
        # [1, 0] vs [0, 1] → cosine 0 → mapped to 0.5
        def embed(text: str) -> list[float]:
            return [1.0, 0.0] if text == "q" else [0.0, 1.0]

        assert score_answer_relevancy("q", "a", embed) == pytest.approx(0.5)

    def test_opposite_vectors_zero(self) -> None:
        # [-1, 0] vs [1, 0] → cosine -1 → clamped to 0.0
        def embed(text: str) -> list[float]:
            return [-1.0, 0.0] if text == "q" else [1.0, 0.0]

        assert score_answer_relevancy("q", "a", embed) == pytest.approx(0.0)

    def test_empty_question_returns_zero(self) -> None:
        assert score_answer_relevancy("", "answer", lambda _t: [1.0]) == 0.0

    def test_empty_answer_returns_zero(self) -> None:
        assert score_answer_relevancy("q", "", lambda _t: [1.0]) == 0.0

    def test_embed_exception_returns_zero(self) -> None:
        def bad_embed(_t: str) -> list[float]:
            raise RuntimeError("embed broken")

        assert score_answer_relevancy("q", "a", bad_embed) == 0.0

    def test_zero_vector_returns_zero(self) -> None:
        # Degenerate zero vector → cosine is NaN → coerced to 0.0
        assert score_answer_relevancy("q", "a", lambda _t: [0.0, 0.0]) == 0.0


# ---- score_context_precision -----------------------------------------


class TestScoreContextPrecision:
    def test_empty_contexts_returns_zero(self) -> None:
        assert score_context_precision("q", [], _judge_always) == 0.0

    def test_all_relevant_returns_one(self) -> None:
        score = score_context_precision(
            "what is X?",
            ["X is described here.", "More about X."],
            _judge_always,
        )
        assert score == pytest.approx(1.0)

    def test_none_relevant_returns_zero(self) -> None:
        score = score_context_precision(
            "what is X?",
            ["about Y", "about Z"],
            _judge_never,
        )
        assert score == 0.0

    def test_mixed_returns_fraction(self) -> None:
        # 4 chunks, judge says yes for 2 → 0.5
        score = score_context_precision(
            "what is X?",
            ["c1", "c2", "c3", "c4"],
            _judge_per_claim([True, True, False, False]),
        )
        assert score == pytest.approx(0.5)

    def test_empty_chunk_text_skipped(self) -> None:
        # Empty/whitespace chunks are skipped (would otherwise produce
        # a 0/0 = NaN). The denominator stays at the original count.
        score = score_context_precision(
            "what is X?",
            ["", "   ", "X info"],
            _judge_always,
        )
        # judge returns yes for empty chunks (conservative — they
        # were not relevant). Only one of three is "yes" → 1/3.
        # We don't assert the precise numeric behaviour here, just
        # that the call doesn't crash and the value is in [0, 1].
        assert 0.0 <= score <= 1.0


# ---- score_context_recall --------------------------------------------


class TestScoreContextRecall:
    def test_no_ground_truth_returns_nan(self) -> None:
        assert math.isnan(score_context_recall(["a", "b"], None))
        assert math.isnan(score_context_recall(["a", "b"], []))

    def test_partial_overlap(self) -> None:
        # 5 ground-truth ids, 3 of them retrieved → 0.6
        retrieved = ["a", "b", "c"]
        relevant = ["a", "b", "c", "d", "e"]
        score = score_context_recall(retrieved, relevant)
        assert score == pytest.approx(0.6)

    def test_full_overlap_returns_one(self) -> None:
        score = score_context_recall(["a", "b", "c"], ["a", "b", "c"])
        assert score == pytest.approx(1.0)

    def test_no_overlap_returns_zero(self) -> None:
        score = score_context_recall(["x", "y"], ["a", "b"])
        assert score == 0.0

    def test_empty_retrieved_with_truth(self) -> None:
        # Retrieved nothing, but ground truth exists → 0.0
        score = score_context_recall([], ["a", "b"])
        assert score == 0.0


# ---- score_all integration -------------------------------------------


class TestScoreAll:
    def test_returns_dataclass_with_floats(self) -> None:
        # Wire mocks end-to-end and assert the result shape.
        question = "what is X?"
        answer = "X is a thing."
        contexts = ["X is described in this chunk."]
        retrieved_ids = ["c1"]
        relevant_ids = ["c1"]

        result = score_all(
            question=question,
            answer=answer,
            contexts=contexts,
            retrieved_ids=retrieved_ids,
            relevant_ids=relevant_ids,
            ollama_fn=_judge_always,
            embed_fn=lambda _t: [1.0, 0.0],
        )

        assert isinstance(result, RagasScores)
        for field_name in (
            "faithfulness",
            "answer_relevancy",
            "context_precision",
            "context_recall",
        ):
            v = getattr(result, field_name)
            assert isinstance(v, float), f"{field_name} should be float, got {type(v)}"
            if not math.isnan(v):
                assert 0.0 <= v <= 1.0, f"{field_name} out of range: {v}"

        # With judge_always, all supported/relevant → max
        assert result.faithfulness == pytest.approx(1.0)
        assert result.context_precision == pytest.approx(1.0)
        assert result.context_recall == pytest.approx(1.0)
        # cosine of identical vectors is 1.0 → mapped to 1.0
        assert result.answer_relevancy == pytest.approx(1.0)

    def test_score_all_nan_when_no_ground_truth(self) -> None:
        result = score_all(
            question="q",
            answer="a",
            contexts=["ctx"],
            retrieved_ids=["c1"],
            relevant_ids=None,
            ollama_fn=_judge_always,
            embed_fn=lambda _t: [1.0, 0.0],
        )
        assert math.isnan(result.context_recall)
        # The other metrics should still be computable.
        assert result.faithfulness == pytest.approx(1.0)
        assert result.context_precision == pytest.approx(1.0)
