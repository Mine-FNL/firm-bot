"""firm-bot: multi-tenant local-first chatbot builder for professional services firms.

Public API surface lives in submodules:
- firm_bot.cli: command-line entry point (firm, ingest, query, serve, eval)
- firm_bot.api: FastAPI app (mounted at ``firm_bot.api:app``)
- firm_bot.ingest: PDF / EML / DOCX extraction
- firm_bot.chunk: structure-aware chunking
- firm_bot.retrieve: hybrid BM25 + dense retrieval
- firm_bot.answer: citation-required prompts + guards
- firm_bot.store: per-tenant storage (Chroma + filesystem)
- firm_bot.config: configuration dataclasses + loaders

RAG-first design. v0.1 does NOT fine-tune a base model; it grounds every
answer in retrieved chunks from the tenant's own document corpus. Fine-tuning
(LoRA) is on the v0.2 roadmap.
"""
from __future__ import annotations

__version__ = "0.1.0"
