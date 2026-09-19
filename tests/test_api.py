"""End-to-end API tests.

These tests exercise the FastAPI app against the mocked Ollama fixture,
so no real model load is required.

Run with:
    pytest tests/test_api.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(env_data_dir: Path, mock_ollama: object) -> TestClient:
    from firm_bot.api import app

    return TestClient(app)


def test_create_firm_and_ingest(client: TestClient, sample_pdf: Path) -> None:
    # create
    r = client.post(
        "/v1/firms",
        json={"slug": "demo", "name": "Demo LLP"},
    )
    assert r.status_code == 201

    # upload via the API
    with sample_pdf.open("rb") as f:
        r = client.post(
            "/v1/firms/demo/upload",
            files={"file": (sample_pdf.name, f, "application/pdf")},
        )
    assert r.status_code == 200, r.text

    # ingest
    r = client.post("/v1/firms/demo/ingest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chunks_indexed"] >= 1
    assert body["stats"]["files_total"] == 1

    # stats reflect the index
    r = client.get("/v1/firms/demo/stats")
    stats = r.json()
    assert stats["chroma_chunks"] >= 1


def test_query_returns_citation(client: TestClient, sample_pdf: Path) -> None:
    # set up
    client.post("/v1/firms", json={"slug": "demo", "name": "Demo LLP"})
    with sample_pdf.open("rb") as f:
        client.post(
            "/v1/firms/demo/upload",
            files={"file": (sample_pdf.name, f, "application/pdf")},
        )
    client.post("/v1/firms/demo/ingest")

    r = client.post(
        "/v1/firms/demo/query",
        json={"question": "what is the liability cap", "run_guard": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "answer" in body
    assert "hits" in body
    assert len(body["hits"]) >= 1


def test_query_without_ingest_returns_409(client: TestClient) -> None:
    client.post("/v1/firms", json={"slug": "demo", "name": "Demo LLP"})
    r = client.post(
        "/v1/firms/demo/query",
        json={"question": "anything", "run_guard": False},
    )
    assert r.status_code == 409


def test_invalid_slug_rejected(client: TestClient) -> None:
    r = client.post(
        "/v1/firms",
        json={"slug": "INVALID SLUG WITH SPACES", "name": "Acme"},
    )
    assert r.status_code == 422  # Pydantic pattern validation


def test_list_firms(client: TestClient) -> None:
    client.post("/v1/firms", json={"slug": "alpha", "name": "Alpha LLP"})
    client.post("/v1/firms", json={"slug": "beta", "name": "Beta LLP"})
    r = client.get("/v1/firms")
    body = r.json()
    slugs = {f["slug"] for f in body["firms"]}
    assert {"alpha", "beta"}.issubset(slugs)


def test_index_html_served(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "<!DOCTYPE html>" in r.text
    assert "firm-bot" in r.text


def test_health_check(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_stream_query_endpoint(client: TestClient, sample_pdf: Path) -> None:
    """SSE streaming endpoint returns meta + token + done events."""
    client.post("/v1/firms", json={"slug": "demo", "name": "Demo LLP"})
    with sample_pdf.open("rb") as f:
        client.post(
            "/v1/firms/demo/upload",
            files={"file": (sample_pdf.name, f, "application/pdf")},
        )
    client.post("/v1/firms/demo/ingest")

    # The mock_ollama fixture returns a canned response; for the streaming
    # endpoint we just verify the SSE frame structure is correct.
    with client.stream(
        "POST",
        "/v1/firms/demo/query/stream",
        json={"question": "what is the liability cap"},
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        events: list[str] = []
        for line in r.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
        # Should at least contain meta and done (the mock_ollama fixture
        # doesn't actually stream tokens, but the endpoint still emits
        # the meta + done framing).
        assert "meta" in events
        assert "done" in events
