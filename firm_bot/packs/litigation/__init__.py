"""Litigation domain pack for firm-bot.

Opt-in add-on for civil-litigation adversarial-document reading.
Provides:

* :func:`extract_transcript` — deposition/hearing transcripts in
  ``[page:line] Q. … / A. …`` format. Each emitted chunk carries the
  page and line metadata so the answer LLM can cite ``:p.<N>:L<L>``.

* :func:`extract_pleading` — complaints, motions, answers, briefs
  with numbered paragraphs. Each emitted chunk carries the paragraph
  range so the answer LLM can cite ``:¶<start>-¶<end>``.

* :func:`chunk_transcript` / :func:`chunk_pleading` — Q/A-aware and
  paragraph-aware splitters used internally by the extractors and
  exposed for callers that want to re-chunk the text externally.

* :data:`LITIGATION_SYSTEM_PROMPT_SUFFIX` — a prompt fragment to
  append to ``FirmConfig.system_prompt`` when the firm is configured
  for litigation work.

* :func:`register` / :func:`unregister` — wire the pack's extractors
  into ``firm_bot.ingest.common.dispatch`` so ``.txt`` files with the
  ``TX_``/``PL_``/``EX_`` filename prefixes are routed to the right
  extractor when ``firm-bot ingest`` walks the firm's ``source/`` dir.

* :func:`apply_to_firm` — one-shot helper that sets the system-prompt
  suffix on a ``FirmConfig`` and writes it back to disk.

Sample corpus
-------------
A small set of fully-fabricated, public-domain-equivalent litigation
documents lives in :mod:`firm_bot.packs.litigation.sample_corpus` for
demonstration and test fixtures. Parties are placeholder ("ACME CORP",
"BETA CORP") and the legal arguments are generic.
"""

from __future__ import annotations

from pathlib import Path

from ...chunk import Chunk  # noqa: F401  (re-exported below)
from ...config import FirmConfig
from .chunker import chunk_pleading, chunk_transcript
from .extractor import (
    PLEADING_PREFIXES,
    TRANSCRIPT_PREFIX,
    classify,
    extract_pleading,
    extract_transcript,
    register,
    unregister,
)
from .prompt import LITIGATION_SYSTEM_PROMPT_SUFFIX, PROMPT_MARKERS

__all__ = [
    "LITIGATION_SYSTEM_PROMPT_SUFFIX",
    "PLEADING_PREFIXES",
    "PROMPT_MARKERS",
    "TRANSCRIPT_PREFIX",
    "apply_to_firm",
    "chunk_pleading",
    "chunk_transcript",
    "classify",
    "extract_pleading",
    "extract_transcript",
    "register",
    "sample_corpus_dir",
    "unregister",
]

PACK_ID = "litigation"
PACK_VERSION = "0.1.0"
FIRM_BOT_MIN_VERSION = "0.4.0"


def sample_corpus_dir() -> Path:
    """Return the absolute path to the pack's bundled sample corpus.

    The directory contains 4 small fabricated litigation documents:
    one complaint, one motion for summary judgment, one deposition
    excerpt, and one court order. All parties are placeholder
    ("ACME CORP", "BETA CORP"); each file is < 5 KB.
    """
    return Path(__file__).resolve().parent / "sample_corpus"


def apply_to_firm(
    firm_dir: Path,
    *,
    register_dispatch: bool = True,
) -> None:
    """Apply litigation-pack defaults to the firm at ``firm_dir``.

    Loads ``<firm_dir>/config.yaml``, sets ``system_prompt`` to
    :data:`LITIGATION_SYSTEM_PROMPT_SUFFIX`, records the pack id in
    ``extra``, and writes the config back. If
    ``register_dispatch=True`` (default), also calls :func:`register` so
    the pack's extractors are wired into the dispatch table for this
    process.

    Safe to call on a fresh firm (creates the file if missing). Does
    not overwrite a non-empty ``system_prompt`` unless the firm already
    carries a litigation-pack marker (``pack_id`` in ``extra``).
    """
    cfg = FirmConfig.load(firm_dir)
    pack_extra = dict(cfg.extra)
    if pack_extra.get("pack_id") == PACK_ID:
        # already configured — refresh prompt only if blank
        if not cfg.system_prompt:
            cfg.system_prompt = LITIGATION_SYSTEM_PROMPT_SUFFIX
    else:
        cfg.system_prompt = LITIGATION_SYSTEM_PROMPT_SUFFIX
        pack_extra["pack_id"] = PACK_ID
        pack_extra["pack_version"] = PACK_VERSION
        cfg.extra = pack_extra
    cfg.save(firm_dir)
    if register_dispatch:
        register()


def list_sample_corpus() -> list[Path]:
    """Return a sorted list of sample-corpus file paths."""
    sd = sample_corpus_dir()
    if not sd.is_dir():
        return []
    return sorted(p for p in sd.iterdir() if p.is_file() and not p.name.startswith("."))


# Re-export so callers can ``from firm_bot.packs.litigation import Chunk``
# without reaching into ``firm_bot.chunk`` directly.
__all__.append("Chunk")
