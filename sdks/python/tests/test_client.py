"""Unit tests for :mod:`firm_bot_sdk.client`.

All tests use a programmable fake transport (see ``conftest.py``) so
they do not hit a real network. The fake records every request so
each test asserts on both the outbound shape (method, URL, headers,
JSON body) and the inbound parsing (dataclass return values).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from firm_bot_sdk import (
    AuthError,
    FirmBotError,
    FirmSummary,
    NotFoundError,
    QueryResponse,
    RateLimitError,
    ServerError,
    UploadResult,
    ValidationError,
)
from firm_bot_sdk.client import _STATUS_MAP

# --------------------------------------------------------------------- #
# Construction & low-level plumbing                                     #
# --------------------------------------------------------------------- #


def test_client_strips_trailing_slash_and_sends_auth_header(
    make_client: Any, fake_transport: Any
) -> None:
    """``__init__`` normalises the base URL; every request carries the API key."""
    fake_transport.enqueue(200, body={"firms": []})
    client = make_client(base_url="https://firm-bot.test/", api_key="secret-key-xyz")

    firms = client.list_firms()

    assert firms == []
    assert len(fake_transport.requests) == 1
    sent = fake_transport.requests[0]
    # Trailing slash stripped so URL building never produces //v1/...
    assert sent.url == "https://firm-bot.test/v1/firms"
    assert sent.headers.get("X-api-key") == "secret-key-xyz"
    # The SDK also sends a User-Agent for ops visibility — verify it
    # identifies itself rather than the default urllib UA.
    assert "firm-bot-sdk" in sent.headers.get("User-agent", "").lower()


def test_request_uses_get_when_no_body(make_client: Any, fake_transport: Any) -> None:
    """GET requests must not carry a body or content-type header."""
    fake_transport.enqueue(200, body={"firms": []})
    client = make_client()
    client.list_firms()
    sent = fake_transport.requests[0]
    assert sent.method == "GET"
    assert sent.body == b""
    # urllib strips Content-Type on GETs; ensure we don't force one.
    assert "Content-type" not in {k.title() for k in sent.headers}


# --------------------------------------------------------------------- #
# list_firms / create_firm                                              #
# --------------------------------------------------------------------- #


def test_list_firms_returns_typed_summaries(make_client: Any, fake_transport: Any) -> None:
    """``list_firms`` parses each entry into a ``FirmSummary``."""
    fake_transport.enqueue(
        200,
        body={
            "firms": [
                {"slug": "acme", "name": "Acme LLP"},
                {"slug": "globex", "name": "Globex"},
            ]
        },
    )
    client = make_client()
    firms = client.list_firms()
    assert isinstance(firms, list)
    assert all(isinstance(f, FirmSummary) for f in firms)
    assert [(f.slug, f.name) for f in firms] == [("acme", "Acme LLP"), ("globex", "Globex")]


def test_create_firm_posts_correct_payload(make_client: Any, fake_transport: Any) -> None:
    """``create_firm`` POSTs the exact payload the server expects."""
    # ``create_firm`` echoes back the FirmConfig dict — match the
    # real server's full shape so the SDK parses every field.
    fake_transport.enqueue(
        201,
        body={
            "slug": "demo",
            "name": "Demo Firm",
            "system_prompt": "Be helpful.",
            "llm_model": "llama3.1",
            "contact_email": "ops@example.com",
            "notes": "",
            "redact_categories": [],
        },
    )
    client = make_client()
    cfg = client.create_firm(
        "demo",
        "Demo Firm",
        system_prompt="Be helpful.",
        llm_model="llama3.1",
        contact_email="ops@example.com",
    )
    sent = fake_transport.requests[0]
    assert sent.method == "POST"
    assert sent.url == "https://firm-bot.test/v1/firms"
    assert sent.headers.get("Content-type") == "application/json"
    body = json.loads(sent.body)
    assert body == {
        "slug": "demo",
        "name": "Demo Firm",
        "system_prompt": "Be helpful.",
        "llm_model": "llama3.1",
        "contact_email": "ops@example.com",
    }
    assert cfg.slug == "demo"
    assert cfg.system_prompt == "Be helpful."
    # ``redact_categories`` is not in our typed shape — it should be
    # captured in ``extra`` rather than dropped.
    assert cfg.extra.get("redact_categories") == []


# --------------------------------------------------------------------- #
# query                                                                  #
# --------------------------------------------------------------------- #


def test_query_builds_request_with_k_and_run_guard(
    make_client: Any, fake_transport: Any
) -> None:
    """``query`` must include ``k`` and ``run_guard`` in the JSON body."""
    fake_transport.enqueue(200, body=_empty_query_payload())
    client = make_client()
    client.query(
        "acme",
        "What is the indemnification cap?",
        k=8,
        run_guard=False,
        history=[{"role": "user", "content": "earlier question"}],
    )
    sent = fake_transport.requests[0]
    assert sent.method == "POST"
    assert sent.url == "https://firm-bot.test/v1/firms/acme/query"
    payload = json.loads(sent.body)
    assert payload["question"] == "What is the indemnification cap?"
    assert payload["k"] == 8
    assert payload["run_guard"] is False
    assert payload["history"] == [{"role": "user", "content": "earlier question"}]


def test_query_parses_response_into_dataclass(
    make_client: Any, fake_transport: Any
) -> None:
    """``query`` returns a ``QueryResponse`` with the new v0.2 fields populated."""
    fake_transport.enqueue(
        200,
        body={
            "answer": "The cap is $1M.",
            "cited": ["[contract.pdf:p.4]"],
            "hits": [
                {
                    "chunk_id": "c1",
                    "marker": "contract.pdf:p.4",
                    "score": 0.91,
                    "bm25_rank": 1,
                    "dense_rank": 1,
                    "preview": "…cap is $1M…",
                }
            ],
            "issues": [{"claim": "vague", "severity": "warn"}],
            "summary": "ok",
            "confidence": 0.8,
            "latency_ms": 123.4,
            "model": "llama3.1",
            "judge_model": "llama3.1-judge",
            "prompt_injection_suspected": 0,
            "prompt_injection_patterns": [],
            "stage_latency_ms": {"retrieve": 12.0, "answer": 100.0, "guard": 10.0},
        },
    )
    client = make_client()
    resp = client.query("acme", "What is the cap?")

    assert isinstance(resp, QueryResponse)
    assert resp.answer == "The cap is $1M."
    assert resp.cited == ["[contract.pdf:p.4]"]
    assert len(resp.hits) == 1
    assert resp.hits[0].score == pytest.approx(0.91)
    assert resp.prompt_injection_suspected == 0
    assert resp.stage_latency_ms == {
        "retrieve": pytest.approx(12.0),
        "answer": pytest.approx(100.0),
        "guard": pytest.approx(10.0),
    }
    # Raw payload preserved so callers can introspect any server field
    # we haven't modelled yet.
    assert resp.raw["model"] == "llama3.1"


def test_query_defaults_apply_when_omitted(make_client: Any, fake_transport: Any) -> None:
    """Default ``k=6``, ``run_guard=True``, no history."""
    fake_transport.enqueue(200, body=_empty_query_payload())
    client = make_client()
    client.query("acme", "Q?")
    payload = json.loads(fake_transport.requests[0].body)
    assert payload["k"] == 6
    assert payload["run_guard"] is True
    assert "history" not in payload


# --------------------------------------------------------------------- #
# Error mapping                                                          #
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status", "exc_cls"),
    [
        (401, AuthError),
        (403, AuthError),
        (404, NotFoundError),
        (400, ValidationError),
        (422, ValidationError),
        (429, RateLimitError),
        (500, ServerError),
        (502, ServerError),
        (503, ServerError),
    ],
)
def test_status_maps_to_typed_exception(
    make_client: Any, fake_transport: Any, status: int, exc_cls: type[FirmBotError]
) -> None:
    """Every status in the spec maps to the documented exception class."""
    fake_transport.enqueue(status, body={"detail": f"boom {status}"})
    client = make_client()
    with pytest.raises(exc_cls) as ei:
        client.list_firms()
    err = ei.value
    assert err.status == status
    assert err.path == "/v1/firms"
    # The status->class map is the single source of truth for which
    # code raises which class. Assert the map itself stays consistent
    # so refactors don't silently break error semantics.
    if status in _STATUS_MAP:
        assert _STATUS_MAP[status] is exc_cls
    else:
        assert 500 <= status <= 599


def test_auth_error_includes_body_detail(make_client: Any, fake_transport: Any) -> None:
    """Structured error bodies are surfaced on the exception."""
    fake_transport.enqueue(401, body={"detail": "missing api key"})
    client = make_client()
    with pytest.raises(AuthError) as ei:
        client.list_firms()
    assert "missing api key" in str(ei.value)
    assert ei.value.body == {"detail": "missing api key"}


# --------------------------------------------------------------------- #
# Audit log special handling                                             #
# --------------------------------------------------------------------- #


def test_audit_log_csv_returns_raw_string(make_client: Any, fake_transport: Any) -> None:
    """``format='csv'`` must return a raw CSV string, not parsed JSON."""
    csv_payload = (
        "timestamp,request_id,firm_slug\n"
        "2026-01-01T00:00:00Z,rq-1,acme\n"
    )
    fake_transport.enqueue(200, body=csv_payload.encode("utf-8"), content_type="text/csv")
    client = make_client()
    out = client.get_audit_log("acme", format="csv")
    assert isinstance(out, str)
    assert out.startswith("timestamp,request_id,firm_slug")
    sent = fake_transport.requests[0]
    # Server uses ``fmt=`` not ``format=``.
    assert "fmt=csv" in sent.url


def test_audit_log_json_parses_into_entries(make_client: Any, fake_transport: Any) -> None:
    """``format='json'`` parses into a list of ``AuditLogEntry``."""
    fake_transport.enqueue(
        200,
        body=[
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "request_id": "rq-1",
                "firm_slug": "acme",
                "question_hash": "abcd",
                "question_len_chars": 10,
                "answer_len_chars": 20,
                "citation_count": 1,
                "guard_summary": "ok",
                "guard_issue_count": 0,
                "confidence": 0.8,
                "model": "llama3.1",
                "retrieval_latency_ms": 12.0,
                "answer_latency_ms": 100.0,
                "total_latency_ms": 112.0,
                "hit_count": 5,
            }
        ],
    )
    client = make_client()
    entries = client.get_audit_log("acme")
    assert len(entries) == 1
    assert entries[0].firm_slug == "acme"
    assert entries[0].confidence == pytest.approx(0.8)


# --------------------------------------------------------------------- #
# Transport-level edge cases                                             #
# --------------------------------------------------------------------- #


def test_network_error_is_wrapped_in_firmbot_error(
    make_client: Any, monkeypatch: Any
) -> None:
    """A URLError (e.g. DNS failure) becomes a FirmBotError with cause."""
    import urllib.error

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise urllib.error.URLError("dns lookup failed")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    client = make_client()
    with pytest.raises(FirmBotError) as ei:
        client.list_firms()
    assert "dns lookup failed" in str(ei.value)
    assert isinstance(ei.value.__cause__, urllib.error.URLError)


def test_timeout_is_surfaced_as_firmbot_error(
    make_client: Any, monkeypatch: Any
) -> None:
    """A socket timeout becomes a FirmBotError, not a raw TimeoutError."""
    import socket

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    client = make_client(timeout_s=2.5)
    with pytest.raises(FirmBotError) as ei:
        client.list_firms()
    assert "2.5" in str(ei.value)
    assert isinstance(ei.value.__cause__, socket.timeout)


# --------------------------------------------------------------------- #
# URL building                                                           #
# --------------------------------------------------------------------- #


def test_path_parameters_are_url_escaped(make_client: Any, fake_transport: Any) -> None:
    """Slugs are URL-escaped so a malformed value cannot break the URL."""
    fake_transport.enqueue(
        200,
        body={
            "slug": "weird/slug with space",
            "name": "Weird",
            "system_prompt": "",
            "llm_model": "",
            "contact_email": "",
            "notes": "",
        },
    )
    client = make_client()
    # Use a deliberately ugly slug to prove escaping kicks in.
    client.get_firm("weird/slug with space")
    sent = fake_transport.requests[0]
    # urllib.parse.quote with safe="" percent-encodes everything —
    # the literal spaces and slashes must NOT appear in the path.
    assert " " not in sent.url
    assert sent.url.startswith("https://firm-bot.test/v1/firms/weird%2Fslug%20with%20space/config")


# --------------------------------------------------------------------- #
# Upload / multipart                                                     #
# --------------------------------------------------------------------- #


def test_upload_file_sends_multipart_body(
    make_client: Any, fake_transport: Any, tmp_path: Path
) -> None:
    """File uploads use multipart/form-data with a filename + content-type."""
    payload_path = tmp_path / "contract.pdf"
    payload_path.write_bytes(b"%PDF-1.4 fake")
    fake_transport.enqueue(200, body={"stored": str(payload_path), "size_bytes": 14})
    client = make_client()
    result = client.upload_file("acme", payload_path)
    assert isinstance(result, UploadResult)
    assert result.size_bytes == 14
    sent = fake_transport.requests[0]
    assert sent.method == "POST"
    assert sent.url == "https://firm-bot.test/v1/firms/acme/upload"
    assert "multipart/form-data" in sent.headers["Content-type"]
    # The encoded body must carry the filename and file bytes.
    body = sent.body
    assert b'name="file"' in body
    assert b'filename="contract.pdf"' in body
    assert b"%PDF-1.4 fake" in body


# --------------------------------------------------------------------- #
# Helpers                                                                #
# --------------------------------------------------------------------- #


def _empty_query_payload() -> dict[str, Any]:
    """The smallest valid query response — used for request-shape tests."""
    return {
        "answer": "",
        "cited": [],
        "hits": [],
        "issues": [],
        "summary": "ok",
        "confidence": 0.0,
        "latency_ms": 0.0,
        "model": "",
        "prompt_injection_suspected": 0,
        "prompt_injection_patterns": [],
        "stage_latency_ms": {},
    }
