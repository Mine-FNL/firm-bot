"""Tests for input validation hardening on Pydantic request models.

These tests pin the operator-controlled string caps added in the
hardening pass — every endpoint that accepts user input must reject
overlong or empty values BEFORE the request reaches the LLM or the
embedding model. A successful bypass would be either a DoS vector
(10 MB question → 10 MB embed call) or a corruption vector (zero-
length slug → regex match but meaningless directory name).

Coverage:

  - CreateFirmRequest: slug pattern + length, name length,
    system_prompt length, contact_email length, llm_model length
  - QueryRequest / StreamQueryRequest: question min/max, history
    length, k range
  - BulkQueryItem: question, history, k, id (id capped at 64 so a
    UUID fits but arbitrary long strings cannot leak into the
    audit log)

The tests don't cover every edge of Pydantic itself; they pin the
specific bounds firm-bot chose so a future refactor can't quietly
loosen them.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(env_data_dir: Path, mock_ollama: object) -> TestClient:
    from firm_bot.api import app

    return TestClient(app)


# ---- CreateFirmRequest ----------------------------------------------


def test_create_firm_slug_too_long_rejected(client: TestClient) -> None:
    """Slug capped at 42 chars (regex enforces 2-40 alphanum + 2 padding)."""
    long_slug = "a" * 50  # 50 chars, exceeds the 42-char cap
    r = client.post(
        "/v1/firms",
        json={"slug": long_slug, "name": "Test"},
    )
    assert r.status_code == 422, r.text


def test_create_firm_slug_too_short_rejected(client: TestClient) -> None:
    """Slug requires min 2 chars — single char rejected."""
    r = client.post(
        "/v1/firms",
        json={"slug": "a", "name": "Test"},
    )
    assert r.status_code == 422


def test_create_firm_slug_path_traversal_rejected(client: TestClient) -> None:
    """Slug pattern requires [a-z0-9_-] only — dots, slashes, .. rejected."""
    for bad in ("../etc", "foo/bar", "foo.bar", "foo bar", "FOO", ""):
        r = client.post(
            "/v1/firms",
            json={"slug": bad, "name": "Test"},
        )
        assert r.status_code == 422, f"slug {bad!r} should have been rejected"


def test_create_firm_name_too_long_rejected(client: TestClient) -> None:
    """Name capped at 200 chars."""
    r = client.post(
        "/v1/firms",
        json={"slug": "demo", "name": "x" * 300},
    )
    assert r.status_code == 422


def test_create_firm_system_prompt_too_long_rejected(client: TestClient) -> None:
    """System prompt capped at 20 KB (rejects accidental file drops)."""
    r = client.post(
        "/v1/firms",
        json={"slug": "demo", "name": "Test", "system_prompt": "x" * 25_000},
    )
    assert r.status_code == 422


def test_create_firm_llm_model_too_long_rejected(client: TestClient) -> None:
    """llm_model capped at 200 chars."""
    r = client.post(
        "/v1/firms",
        json={"slug": "demo", "name": "Test", "llm_model": "x" * 300},
    )
    assert r.status_code == 422


def test_create_firm_contact_email_too_long_rejected(client: TestClient) -> None:
    """contact_email capped at 320 chars (RFC 5321 max email length)."""
    r = client.post(
        "/v1/firms",
        json={"slug": "demo", "name": "Test", "contact_email": "x" * 400},
    )
    assert r.status_code == 422


def test_create_firm_minimal_valid_passes(client: TestClient) -> None:
    """A minimal valid request succeeds (sanity check for the bounds above)."""
    r = client.post(
        "/v1/firms",
        json={"slug": "demo", "name": "Test"},
    )
    assert r.status_code == 201


# ---- QueryRequest ----------------------------------------------------


def _setup_demo(client: TestClient) -> None:
    """Create + ingest a demo firm so /query has chunks to retrieve."""
    client.post("/v1/firms", json={"slug": "demo", "name": "Test"})
    # We don't actually upload+ingest here; the tests below just hit
    # /query and rely on the empty-collection 409 path. Query
    # validation happens before retrieval, so a 409 here is fine —
    # what matters is that we never reach the embed/answer stages.


def test_query_empty_question_rejected(client: TestClient) -> None:
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query",
        json={"question": "", "run_guard": False},
    )
    assert r.status_code == 422


def test_query_question_too_long_rejected(client: TestClient) -> None:
    """Question capped at 4096 chars — anything larger is a DoS attempt."""
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query",
        json={"question": "x" * 5000, "run_guard": False},
    )
    assert r.status_code == 422


def test_query_history_too_long_rejected(client: TestClient) -> None:
    """History capped at 40 messages."""
    _setup_demo(client)
    history = [{"role": "user", "content": "x"} for _ in range(50)]
    r = client.post(
        "/v1/firms/demo/query",
        json={"question": "test", "history": history, "run_guard": False},
    )
    assert r.status_code == 422


def test_query_k_too_large_rejected(client: TestClient) -> None:
    """k must be in [1, 100]."""
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query",
        json={"question": "test", "k": 500, "run_guard": False},
    )
    assert r.status_code == 422


def test_query_k_zero_rejected(client: TestClient) -> None:
    """k must be >= 1."""
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query",
        json={"question": "test", "k": 0, "run_guard": False},
    )
    assert r.status_code == 422


def test_query_k_negative_rejected(client: TestClient) -> None:
    """k must be >= 1."""
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query",
        json={"question": "test", "k": -5, "run_guard": False},
    )
    assert r.status_code == 422


def test_stream_query_empty_question_rejected(client: TestClient) -> None:
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query/stream",
        json={"question": ""},
    )
    assert r.status_code == 422


def test_stream_query_question_too_long_rejected(client: TestClient) -> None:
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query/stream",
        json={"question": "x" * 5000},
    )
    assert r.status_code == 422


# ---- BulkQueryItem --------------------------------------------------


def test_bulk_query_item_question_too_long_rejected(client: TestClient) -> None:
    """Each bulk item's question must respect the 4096 char cap."""
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query/bulk",
        json={"items": [{"question": "x" * 5000, "run_guard": False}]},
    )
    assert r.status_code == 422


def test_bulk_query_item_id_too_long_rejected(client: TestClient) -> None:
    """Bulk item ``id`` capped at 64 chars (UUID is 36 chars; this is the
    practical max anyone should send)."""
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query/bulk",
        json={
            "items": [
                {"id": "x" * 100, "question": "test", "run_guard": False},
            ],
        },
    )
    assert r.status_code == 422


def test_bulk_query_item_k_out_of_range_rejected(client: TestClient) -> None:
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query/bulk",
        json={
            "items": [
                {"question": "test", "k": 500, "run_guard": False},
            ],
        },
    )
    assert r.status_code == 422


def test_bulk_query_valid_items_pass_validation(client: TestClient) -> None:
    """A well-formed bulk request with valid items passes validation."""
    _setup_demo(client)
    r = client.post(
        "/v1/firms/demo/query/bulk",
        json={
            "items": [
                {"id": "a", "question": "what?", "run_guard": False, "k": 3},
            ],
        },
    )
    # We don't care about the response body here (the firm has no
    # chunks so it'll 409 on retrieval); we only need to confirm
    # validation passed.
    assert r.status_code != 422
