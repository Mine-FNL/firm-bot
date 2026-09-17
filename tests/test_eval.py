"""Tests for the faithfulness eval harness."""
from __future__ import annotations

from pathlib import Path


def test_eval_runs_against_mock_ollama(
    env_data_dir: Path, mock_ollama: object, sample_pdf: Path, tmp_path: Path
) -> None:
    from fastapi.testclient import TestClient

    from firm_bot.api import app

    # set up firm + ingest
    client = TestClient(app)
    client.post("/v1/firms", json={"slug": "demo", "name": "Demo LLP"})
    with sample_pdf.open("rb") as f:
        client.post(
            "/v1/firms/demo/upload",
            files={"file": (sample_pdf.name, f, "application/pdf")},
        )
    client.post("/v1/firms/demo/ingest")

    # write fixture
    fixture = tmp_path / "cases.json"
    fixture.write_text(
        """{
          "cases": [
            {"question": "liability cap", "expected_sources": ["sample_contract"], "expected_keywords": []},
            {"question": "alpha alpha alpha", "expected_sources": [], "expected_keywords": ["alpha"]}
          ]
        }"""
    )

    r = client.post(
        "/v1/firms/demo/eval",
        json={
            "cases": [
                {"question": "liability cap", "expected_sources": ["sample_contract"], "expected_keywords": []},
                {"question": "alpha alpha alpha", "expected_sources": [], "expected_keywords": ["alpha"]},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["aggregate"]["cases"] == 2
    assert "pass_rate" in body["aggregate"]
    assert "rows" in body
    assert len(body["rows"]) == 2
