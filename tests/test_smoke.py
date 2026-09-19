"""Smoke tests for the chunker, retrieval shape, and guard parser.

Run with:
    pytest tests/test_smoke.py -q
"""

from __future__ import annotations

import json
import unittest

import pytest


class TestChunker:
    """The structure-aware chunker is the most contract-sensitive piece."""

    def test_splits_on_section_heading(self) -> None:
        from firm_bot.chunk import chunk_documents
        from firm_bot.ingest.common import Document

        doc = Document(
            doc_id="t1",
            text=(
                "Article I — Definitions\n"
                "Confidential Information means information disclosed by either party.\n\n"
                "Article II — Services\n"
                "Provider shall deliver the services described in Schedule A.\n"
            ),
        )
        chunks = chunk_documents([doc], chunk_size=400, overlap=40)
        assert len(chunks) >= 2
        assert chunks[0].text.startswith("Article I")

    def test_splits_on_title_case_heading(self) -> None:
        """Standalone Title Case headings (no Article/Section prefix) split."""
        from firm_bot.chunk import chunk_documents
        from firm_bot.ingest.common import Document

        doc = Document(
            doc_id="t1",
            text=(
                "Governing Law\n"
                "This Agreement is governed by Delaware law.\n\n"
                "Term\n"
                "This Agreement remains in effect for three years.\n"
            ),
        )
        chunks = chunk_documents([doc], chunk_size=400, overlap=40)
        assert len(chunks) >= 2
        assert chunks[0].text.startswith("Governing Law")

    def test_long_section_splits_at_sentence_boundary(self) -> None:
        from firm_bot.chunk import chunk_documents
        from firm_bot.ingest.common import Document

        # 3 sentences * ~120 chars each, with a long section
        body = (
            "Section 4.2 — Limitation of Liability. "
            "Each party agrees that liability shall not exceed fees paid in the prior twelve months. "
            "Neither party shall be liable for any indirect or consequential damages. "
            "This limitation applies to all claims under this agreement. "
            "The parties acknowledge that the limitations herein are a reasonable allocation of risk."
        )
        chunks = chunk_documents(
            [Document(doc_id="t2", text=body)],
            chunk_size=180,
            overlap=20,
        )
        assert len(chunks) >= 2
        for c in chunks:
            assert not c.text.endswith(" ")
            assert not c.text.endswith("-")


class TestRetrievalShape:
    """Verify the RetrievalHit / hybrid wiring without spinning up models."""

    def test_marker_formatter(self) -> None:
        from firm_bot.answer.prompt import _marker_from_meta

        assert _marker_from_meta({"source_name": "x.pdf", "page": 4}) == "[x.pdf:p.4]"
        assert (
            _marker_from_meta(
                {"source_name": "m.eml", "extractor": "eml", "message_id": "<abc@example.com>"}
            )
            == "[m.eml#<abc@example.com>]"
        )
        assert (
            _marker_from_meta(
                {
                    "source_name": "d.docx",
                    "extractor": "docx",
                    "section": 2,
                    "heading": "Definitions",
                }
            )
            == '[d.docx§2 "Definitions"]'
        )


class TestGuardParser:
    """The guard's JSON parser must be tolerant of fences and prose."""

    def test_parses_clean_json(self) -> None:
        from firm_bot.answer.guard import _parse_verdict

        raw = json.dumps(
            {"issues": [{"claim": "x", "marker": "y", "verdict": "supported"}], "summary": "ok"}
        )
        issues, summary, ok = _parse_verdict(raw)
        assert ok
        assert summary == "ok"
        assert len(issues) == 1

    def test_parses_fenced_json(self) -> None:
        from firm_bot.answer.guard import _parse_verdict

        raw = "```json\n" + json.dumps({"issues": [], "summary": "needs_review"}) + "\n```"
        issues, summary, ok = _parse_verdict(raw)
        assert ok
        assert summary == "needs_review"
        assert issues == []

    def test_falls_back_when_no_json(self) -> None:
        from firm_bot.answer.guard import _parse_verdict

        _issues, summary, ok = _parse_verdict("the judge was confused, no JSON here")
        assert not ok
        assert summary == "needs_review"


class TestConfigValidation:
    """RootConfig and FirmConfig must reject obviously-invalid values."""

    def test_root_config_validates_chunk_size(self) -> None:
        from firm_bot.config import RootConfig
        from firm_bot.errors import ConfigError

        cfg = RootConfig(data_dir="./x", chunk_size=10)
        with pytest.raises(ConfigError):
            cfg.validate()

    def test_root_config_validates_overlap(self) -> None:
        from firm_bot.config import RootConfig
        from firm_bot.errors import ConfigError

        cfg = RootConfig(data_dir="./x", chunk_size=200, chunk_overlap=200)
        with pytest.raises(ConfigError):
            cfg.validate()

    def test_root_config_validates_hybrid_weights(self) -> None:
        from firm_bot.config import RootConfig
        from firm_bot.errors import ConfigError

        cfg = RootConfig(data_dir="./x", hybrid_bm25_weight=2.0)
        with pytest.raises(ConfigError):
            cfg.validate()

    def test_root_config_validates_ollama_host(self) -> None:
        from firm_bot.config import RootConfig
        from firm_bot.errors import ConfigError

        cfg = RootConfig(data_dir="./x", ollama_host="not-a-url")
        with pytest.raises(ConfigError):
            cfg.validate()

    def test_firm_config_validates_slug(self) -> None:
        from firm_bot.config import FirmConfig
        from firm_bot.errors import InvalidSlugError

        cfg = FirmConfig(slug="INVALID SLUG", name="Acme")
        with pytest.raises(InvalidSlugError):
            cfg.validate()


if __name__ == "__main__":
    unittest.main()
