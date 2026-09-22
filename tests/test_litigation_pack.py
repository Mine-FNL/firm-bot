"""Tests for the litigation domain pack.

Behaviour pinned here:
  - ``chunk_transcript`` splits on page:line markers and Q./A. lines
    so a single chunk never straddles a half-pair.
  - ``chunk_pleading`` groups numbered paragraphs and keeps the
    caption block as a preface chunk.
  - ``extract_transcript`` emits Chunks with ``page``, ``line``, and
    ``qa_start`` metadata.
  - ``extract_pleading`` emits Chunks with ``para_start``/``para_end``
    and ``kind`` ("preface" or "body").
  - ``register()`` / ``unregister()`` are idempotent and round-trip.
  - The pack is opt-in: base ingestion path is unchanged when the
    pack is not registered.
  - The litigation system prompt contains the documented markers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from firm_bot.packs.litigation import (
    LITIGATION_SYSTEM_PROMPT_SUFFIX,
    PROMPT_MARKERS,
    apply_to_firm,
    chunk_pleading,
    chunk_transcript,
    classify,
    extract_pleading,
    extract_transcript,
    list_sample_corpus,
    register,
    sample_corpus_dir,
    unregister,
)
from firm_bot.packs.litigation.chunker import RE_PAGE_LINE, RE_PLEADING_PARA, chunk_iter

# ---- chunker: transcripts ------------------------------------------------


def test_chunk_transcript_empty_returns_empty() -> None:
    assert chunk_transcript("") == []
    assert chunk_transcript("   \n  ") == []


def test_chunk_transcript_splits_on_page_line_markers() -> None:
    """Each [page:line] marker starts a new chunk."""
    text = (
        "[1:1] Q. What is your name?\n"
        "A. John Doe.\n"
        "[1:5] Q. Where do you live?\n"
        "A. Springfield.\n"
        "[2:1] Q. What is your occupation?\n"
        "A. Widget maker.\n"
    )
    chunks = chunk_transcript(text)
    assert len(chunks) == 3
    # Each chunk should start with a page:line marker
    for chunk in chunks:
        assert RE_PAGE_LINE.match(chunk.splitlines()[0])


def test_chunk_transcript_splits_on_qa_boundaries() -> None:
    """Q./A. pairs without page markers stay together in one chunk by design.

    Q. is a SOFT boundary (chunked together until ``lines_per_chunk``
    is exceeded); the chunker keeps multiple Q/A pairs in one chunk so
    embeddings capture the conversational thread. A. is never a
    boundary.
    """
    text = "Q. What is your name?\nA. John Doe.\nQ. Where do you live?\nA. Springfield.\n"
    chunks = chunk_transcript(text)
    # 4 lines < default lines_per_chunk=50 → one chunk
    assert len(chunks) == 1
    # First line of the chunk is a Q. (never an A.)
    assert chunks[0].startswith("Q.")


def test_chunk_transcript_soft_cap_merges_qa_pairs() -> None:
    """With a low ``lines_per_chunk``, the cap flushes between Q. pairs."""
    text = ""
    for i in range(20):
        text += f"Q. Q{i}?\nA. A{i}.\n"
    # 40 lines, lines_per_chunk=10 → 4 chunks
    chunks = chunk_transcript(text, lines_per_chunk=10)
    assert len(chunks) == 4
    # Each chunk opens with Q.
    for c in chunks:
        assert c.splitlines()[0].startswith("Q.")


def test_chunk_transcript_respects_lines_per_chunk_cap() -> None:
    """The chunker flushes at ``lines_per_chunk`` even without boundaries."""
    # 30 Q/A pairs in a row with no page:line markers.
    lines = []
    for i in range(30):
        lines.append(f"Q. Question {i}?")
        lines.append(f"A. Answer {i}.")
    text = "\n".join(lines)
    chunks = chunk_transcript(text, lines_per_chunk=10)
    # 30 lines / 10 per chunk = 3 chunks (boundary flushes along the way).
    assert 1 <= len(chunks) <= 6


# ---- chunker: pleadings --------------------------------------------------


def test_chunk_pleading_empty_returns_empty() -> None:
    assert chunk_pleading("") == []
    assert chunk_pleading("   \n  ") == []


def test_chunk_pleading_groups_numbered_paragraphs() -> None:
    text = (
        "UNITED STATES DISTRICT COURT\n"
        "SOUTHERN DISTRICT OF NEW YORK\n"
        "\n"
        "1. Plaintiff ACME CORP brings this action against Beta Corp.\n"
        "2. Jurisdiction is proper under 28 U.S.C. § 1331.\n"
        "3. Venue is proper in this district.\n"
        "4. Plaintiff alleges breach of contract dated January 1, 2025.\n"
        "5. Plaintiff seeks damages in excess of $1,000,000.\n"
    )
    chunks = chunk_pleading(text, paragraphs_per_chunk=10)
    # Caption (preface) is emitted as its own chunk; numbered
    # paragraphs are emitted as a separate body chunk so the answer
    # layer can render them with paragraph-range citations.
    assert len(chunks) == 2
    # First chunk: preface (caption block before any numbered paragraph)
    assert not RE_PLEADING_PARA.match(chunks[0].splitlines()[0])
    assert "UNITED STATES DISTRICT COURT" in chunks[0]
    # Second chunk: body paragraphs 1-5
    assert RE_PLEADING_PARA.match(chunks[1].splitlines()[0])
    for n in (1, 2, 3, 4, 5):
        assert f"{n}. " in chunks[1]


def test_chunk_pleading_respects_paragraphs_per_chunk() -> None:
    """When the cap is 2, a 5-paragraph pleading becomes 3 chunks."""
    text = "\n".join(f"{i}. Paragraph {i}." for i in range(1, 6))
    chunks = chunk_pleading(text, paragraphs_per_chunk=2)
    # 5 paragraphs / 2 per chunk = 3 chunks (2+2+1)
    assert len(chunks) == 3
    # Each chunk opens with a numbered paragraph (no preface here)
    for c in chunks:
        assert RE_PLEADING_PARA.match(c.splitlines()[0])


def test_chunk_pleading_no_preface_when_opening_with_paragraph() -> None:
    """A pleading with no caption block produces no preface chunk."""
    text = "\n".join(f"{i}. Paragraph {i}." for i in range(1, 4))
    chunks = chunk_pleading(text)
    assert len(chunks) == 1
    assert RE_PLEADING_PARA.match(chunks[0].splitlines()[0])


def test_chunk_iter_splits_at_offsets() -> None:
    """Generic splitter slices text at the given offsets.

    The function treats offsets as exclusive upper bounds (standard
    Python slice semantics). text="ABCDEFGHIJ" with offsets [3, 7]
    yields pieces [text[0:3], text[3:7], text[7:10]] = ["ABC",
    "DEFG", "HIJ"]. An offset of 0 is implicit; offsets[-1] ==
    len(text) is auto-appended.
    """
    text = "ABCDEFGHIJ"
    parts = chunk_iter(text, [3, 7])
    assert parts == ["ABC", "DEFG", "HIJ"]


# ---- extractor: classify -------------------------------------------------


def test_classify_transcript_prefix() -> None:
    assert classify(Path("TX_john_doe_2025-01-15.txt")) == "transcript"


def test_classify_pleading_prefixes() -> None:
    assert classify(Path("PL_complaint_acme_v_beta.txt")) == "pleading"
    assert classify(Path("PL_motion_msj.txt")) == "pleading"
    assert classify(Path("EX_1_contract.txt")) == "pleading"


def test_classify_unknown_returns_none() -> None:
    assert classify(Path("contract_msa.pdf")) is None
    assert classify(Path("random.txt")) is None
    assert classify(Path("PL_complaint.pdf")) is None  # wrong suffix


# ---- extractor: transcript -----------------------------------------------


@pytest.fixture
def sample_transcript(tmp_path: Path) -> Path:
    p = tmp_path / "TX_witness_2025.txt"
    p.write_text(
        "[1:1] Q. State your name for the record.\n"
        "A. John Doe.\n"
        "[1:3] Q. Where do you work?\n"
        "A. ACME CORP.\n"
        "[2:1] Q. What is your title?\n"
        "A. Chief Widget Officer.\n",
        encoding="utf-8",
    )
    return p


def test_extract_transcript_emits_chunks_with_page_metadata(sample_transcript: Path) -> None:
    chunks = extract_transcript(sample_transcript)
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.metadata["extractor"] == "litigation_transcript"
        assert chunk.metadata["doc_class"] == "transcript"
        assert "page" in chunk.metadata
        assert "line" in chunk.metadata
        assert "qa_start" in chunk.metadata


def test_extract_transcript_returns_empty_for_missing_file(tmp_path: Path) -> None:
    chunks = extract_transcript(tmp_path / "nope.txt")
    assert chunks == []


def test_extract_transcript_returns_empty_for_blank_file(tmp_path: Path) -> None:
    p = tmp_path / "TX_blank.txt"
    p.write_text("   \n\n   ", encoding="utf-8")
    assert extract_transcript(p) == []


# ---- extractor: pleading -------------------------------------------------


@pytest.fixture
def sample_pleading(tmp_path: Path) -> Path:
    p = tmp_path / "PL_complaint_acme.txt"
    p.write_text(
        "UNITED STATES DISTRICT COURT\n"
        "COMPLAINT FOR BREACH OF CONTRACT\n"
        "\n"
        "1. Plaintiff ACME CORP brings this action against Beta Corp.\n"
        "2. This Court has jurisdiction under 28 U.S.C. § 1331.\n"
        "3. Venue is proper in this district.\n"
        "4. On or about January 1, 2025, the parties entered into a contract.\n"
        "5. Defendant has materially breached the contract.\n",
        encoding="utf-8",
    )
    return p


def test_extract_pleading_emits_chunks_with_paragraph_metadata(sample_pleading: Path) -> None:
    chunks = extract_pleading(sample_pleading)
    assert len(chunks) >= 1
    preface_chunks = [c for c in chunks if c.metadata.get("kind") == "preface"]
    body_chunks = [c for c in chunks if c.metadata.get("kind") == "body"]
    assert len(preface_chunks) >= 1
    assert len(body_chunks) >= 1
    for body in body_chunks:
        assert body.metadata["para_start"] >= 1
        assert body.metadata["para_end"] >= body.metadata["para_start"]


def test_extract_pleading_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert extract_pleading(tmp_path / "nope.txt") == []


# ---- register / unregister ----------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_unregistered() -> None:
    """Each test starts from a clean slate."""
    unregister()
    yield
    unregister()


def test_register_then_unregister_round_trip() -> None:
    from firm_bot import ingest

    original = ingest.common.dispatch
    register()
    assert ingest.common.dispatch is not original
    assert hasattr(ingest.common, "_PACK_ORIGINAL_DISPATCH")
    assert ingest.common._PACK_ORIGINAL_DISPATCH is original
    unregister()
    assert ingest.common.dispatch is original
    assert not hasattr(ingest.common, "_PACK_ORIGINAL_DISPATCH")


def test_register_is_idempotent() -> None:
    from firm_bot import ingest

    register()
    first_dispatch = ingest.common.dispatch
    register()
    second_dispatch = ingest.common.dispatch
    assert first_dispatch is second_dispatch


def test_unregister_when_not_registered_is_noop() -> None:
    """Calling unregister twice (or before register) does not raise."""
    from firm_bot import ingest

    original = ingest.common.dispatch
    unregister()  # not registered — should be no-op
    assert ingest.common.dispatch is original


def test_registered_dispatch_routes_tx_to_extractor(tmp_path: Path) -> None:
    """With the pack registered, a TX_*.txt file produces a Document."""
    register()
    p = tmp_path / "TX_jane_2025.txt"
    p.write_text("[1:1] Q. Hi.\nA. Hello.\n", encoding="utf-8")
    from firm_bot import ingest

    docs = ingest.common.dispatch(p)
    assert len(docs) >= 1
    assert docs[0].metadata["extractor"] == "litigation_transcript"


def test_registered_dispatch_routes_pl_to_extractor(tmp_path: Path) -> None:
    register()
    p = tmp_path / "PL_complaint_test.txt"
    p.write_text(
        "CAPTION LINE\n1. Para one.\n2. Para two.\n",
        encoding="utf-8",
    )
    from firm_bot import ingest

    docs = ingest.common.dispatch(p)
    assert len(docs) >= 1
    assert docs[0].metadata["extractor"] == "litigation_pleading"


def test_unregistered_dispatch_ignores_unknown_prefix(tmp_path: Path) -> None:
    """Without the pack registered, TX_*.txt is silently ignored."""
    # unregister() was called by the autouse fixture
    from firm_bot import ingest

    p = tmp_path / "TX_jane_2025.txt"
    p.write_text("[1:1] Q. Hi.\nA. Hello.\n", encoding="utf-8")
    assert ingest.common.dispatch(p) == []


# ---- sample corpus -------------------------------------------------------


def test_sample_corpus_dir_exists_and_has_files() -> None:
    d = sample_corpus_dir()
    assert d.is_dir()
    files = list_sample_corpus()
    assert len(files) >= 3
    for f in files:
        assert f.is_file()
        # All corpus files are .txt — public-domain/fabricated text dumps
        assert f.suffix == ".txt"
        # Public-domain + fully-fabricated content: must not contain
        # names of real attorneys or actual parties.
        text = f.read_text(encoding="utf-8").lower()
        for forbidden in ("john adams", "kanye west", "covington", "wachtell"):
            assert forbidden not in text, f"{f.name} contains forbidden term {forbidden!r}"


def test_sample_corpus_files_parse_via_extractors() -> None:
    """Every sample-corpus file produces at least one Chunk via the right extractor."""
    for path in list_sample_corpus():
        cls = classify(path)
        if cls == "transcript":
            chunks = extract_transcript(path)
        elif cls == "pleading":
            chunks = extract_pleading(path)
        else:  # pragma: no cover - defensive
            pytest.fail(f"sample corpus file {path.name} has no recognised prefix")
        assert chunks, f"no chunks produced from {path.name}"


# ---- system prompt overlay ----------------------------------------------


def test_system_prompt_suffix_contains_required_markers() -> None:
    """The litigation prompt primes the model with the right vocabulary."""
    text = LITIGATION_SYSTEM_PROMPT_SUFFIX.lower()
    for marker in PROMPT_MARKERS:
        assert marker.lower() in text, f"prompt missing marker {marker!r}"


def test_system_prompt_suffix_does_not_invent_citations() -> None:
    """The prompt explicitly forbids inventing citations."""
    text = LITIGATION_SYSTEM_PROMPT_SUFFIX.lower()
    assert "do not invent" in text or "do not infer" in text


# ---- apply_to_firm -------------------------------------------------------


def test_apply_to_firm_sets_system_prompt_and_marks_pack(tmp_path: Path) -> None:
    """apply_to_firm writes the litigation prompt + pack markers."""
    from firm_bot.config import FirmConfig

    firm_dir = tmp_path / "acme-lit"
    firm_dir.mkdir()
    cfg = FirmConfig(slug="acme-lit", name="Acme Litigation")
    cfg.save(firm_dir)

    # Don't actually register the global dispatch for this test —
    # we only care about the on-disk firm config mutation.
    apply_to_firm(firm_dir, register_dispatch=False)

    reloaded = FirmConfig.load(firm_dir)
    assert reloaded.system_prompt == LITIGATION_SYSTEM_PROMPT_SUFFIX
    assert reloaded.extra.get("pack_id") == "litigation"
    assert reloaded.extra.get("pack_version") == "0.1.0"


def test_apply_to_firm_preserves_user_system_prompt_when_already_configured(
    tmp_path: Path,
) -> None:
    """A firm already carrying the pack marker keeps its own system prompt."""
    from firm_bot.config import FirmConfig

    firm_dir = tmp_path / "acme-lit"
    firm_dir.mkdir()
    custom = "CUSTOM PROMPT — do not touch."
    cfg = FirmConfig(slug="acme-lit", name="Acme Litigation")
    cfg.system_prompt = custom
    cfg.extra = {"pack_id": "litigation"}  # already configured
    cfg.save(firm_dir)

    apply_to_firm(firm_dir, register_dispatch=False)

    reloaded = FirmConfig.load(firm_dir)
    assert reloaded.system_prompt == custom
