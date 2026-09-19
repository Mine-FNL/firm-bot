"""Shared pytest fixtures.

The test suite runs without Ollama by default — the ``mock_ollama`` and
``mock_judge`` fixtures monkeypatch ``httpx`` so the chat / judge
clients see deterministic responses. Set ``FIRM_BOT_RUN_OLLAMA_TESTS=1``
to skip mocking and hit a real Ollama endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

# ---- data dirs ---------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """A clean ``<tmp>/data`` directory with a config.yaml ready."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.yaml").write_text(
        f"data_dir: {data!s}\n"
        + "ollama_host: http://mock-ollama:11434\n"
        + "embedding_model: sentence-transformers/all-MiniLM-L6-v2\n"
        + "llm_model: mock-llm\n"
        + "llm_judge_model: mock-judge\n"
        # Rate limit cranked up for the test suite. The default
        # 10 RPS / 20 burst is sized for a single remote user; the
        # e2e tests fire dozens of requests in a row from one
        # loopback client (the bulk endpoint alone does 5 ingest
        # ops + 3 query items + 1 health check per scenario) and
        # would otherwise 429 each other. Set it well above any
        # realistic test workload so rate-limiting isn't a
        # gate-keeping concern in CI.
        + "rate_limit_rps: 1000.0\n"
        + "rate_limit_burst: 10000\n"
    )
    return data


@pytest.fixture
def env_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path) -> Path:
    monkeypatch.setenv("FIRM_BOT_DATA_DIR", str(tmp_data_dir))
    return tmp_data_dir


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Any:
    """Reset the global rate-limiter bucket map between tests.

    The ``SecurityMiddleware`` holds a single ``RateLimiter`` instance
    for the lifetime of the FastAPI app (created at import time via
    ``_register_middleware``). Without a reset, tokens accumulate and
    the test suite starts hitting 429s on the bulk-query tests.
    """
    try:
        from firm_bot.api.app import app as app_obj
    except Exception:
        # app not yet imported — first test triggers import; the next
        # test gets a reset. This is fine.
        yield
        return

    def _reset() -> None:
        for mw in getattr(app_obj, "user_middleware", []):
            kwargs = getattr(mw, "kwargs", None)
            if isinstance(kwargs, dict):
                rl = kwargs.get("rate_limiter")
                if rl is not None and hasattr(rl, "reset"):
                    rl.reset()
                    return

    _reset()
    yield
    _reset()


# ---- Ollama mock -------------------------------------------------------


@pytest.fixture
def mock_ollama() -> Any:
    """Mock httpx to return canned /api/chat responses.

    Returns a respx router that intercepts POST requests to the Ollama
    chat endpoint. The chat response is the input echo; the judge
    response is a canned "ok" verdict.
    """
    if os.environ.get("FIRM_BOT_RUN_OLLAMA_TESTS") == "1":
        pytest.skip("FIRM_BOT_RUN_OLLAMA_TESTS=1, skipping Ollama mock")

    # Mock the HuggingFace model download so sentence-transformers
    # never reaches the network during tests.
    monkeypatch_hf()

    def chat_handler(request: Any) -> Response:
        import json as _json

        body = _json.loads(request.content)
        messages = body.get("messages", [])
        user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        text = user.get("content", "")
        # Heuristic: if the request mentions "audit" we say we don't know
        if "audit" in text.lower() and "list" not in text.lower():
            answer = "I don't know — no relevant chunks were retrieved."
        else:
            # Echo the last 80 chars of the user content as a stub answer
            answer = (
                "This is a stub answer for tests. "
                "[stub.pdf:p.1] (last input: " + text[-80:].replace("\n", " ") + ")"
            )
        return Response(
            200,
            json={
                "model": body.get("model", "mock"),
                "message": {"role": "assistant", "content": answer},
                "done": True,
            },
        )

    def judge_handler(request: Any) -> Response:
        return Response(
            200,
            json={
                "model": "mock-judge",
                "message": {
                    "role": "assistant",
                    "content": '{"issues": [], "summary": "ok"}',
                },
                "done": True,
            },
        )

    with respx.mock(assert_all_called=False) as router:
        # match any host/port since data_dir may use mock-ollama:11434
        router.post(url__regex=r".*/api/chat$").mock(side_effect=chat_handler)
        # also catch any HuggingFace HEAD probes from sentence-transformers
        # initialisation (the FakeSentenceTransformer below should bypass
        # these but respx doesn't know that until after the first call).
        router.head(url__regex=r".*huggingface\.co.*").mock(return_value=Response(200))
        router.get(url__regex=r".*huggingface\.co.*").mock(
            return_value=Response(200, content=b"{}")
        )
        yield router


def monkeypatch_hf() -> None:
    """Patch sentence-transformers so tests don't touch the network.

    Replaces ``SentenceTransformer.encode`` with a deterministic hash-based
    embedder. Hashing is fast and stable, and gives us cosine-similar
    vectors for near-identical inputs — enough for retrieval smoke tests.
    """
    import hashlib

    class FakeSentenceTransformer:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self._dim = 32

        def encode(self, texts: list[str], **_kwargs: Any) -> Any:
            import numpy as np

            out = np.zeros((len(texts), self._dim), dtype=np.float32)
            for i, t in enumerate(texts):
                h = hashlib.sha256(t.encode("utf-8")).digest()
                # spread the bits across 32 floats
                for j in range(self._dim):
                    out[i, j] = (h[j % len(h)] - 128) / 128.0
            # normalise so cosine behaves
            norms = np.linalg.norm(out, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            return out / norms

    import sys

    st_module = sys.modules.get("sentence_transformers")
    if st_module is not None:
        st_module.SentenceTransformer = FakeSentenceTransformer  # type: ignore[attr-defined]


# ---- sample documents --------------------------------------------------


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Generate a tiny multi-section PDF using reportlab."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    out = tmp_path / "sample_contract.pdf"
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(out),
        pagesize=LETTER,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )
    flow = [
        Paragraph("Master Services Agreement", styles["Heading1"]),
        Spacer(1, 12),
        Paragraph("Article I — Definitions", styles["Heading2"]),
        Paragraph(
            "Confidential Information means any non-public information "
            "disclosed by one party to the other in writing or orally that "
            "is designated as confidential.",
            styles["BodyText"],
        ),
        Spacer(1, 6),
        Paragraph("Section 4.2 — Limitation of Liability", styles["Heading2"]),
        Paragraph(
            "NEITHER PARTY'S AGGREGATE LIABILITY ARISING OUT OF THIS "
            "AGREEMENT SHALL EXCEED THE FEES PAID BY CUSTOMER TO VENDOR "
            "IN THE TWELVE (12) MONTHS PRECEDING THE CLAIM.",
            styles["BodyText"],
        ),
    ]
    doc.build(flow)
    return out


@pytest.fixture
def sample_eml(tmp_path: Path) -> Path:
    """Write a tiny .eml file with RFC 822 headers and a plain-text body."""
    out = tmp_path / "sample_email.eml"
    out.write_text(
        "From: alice@example.com\r\n"
        "To: bob@example.com\r\n"
        "Subject: Audit findings for Q3\r\n"
        "Date: Mon, 5 Mar 2026 10:00:00 -0500\r\n"
        "Message-ID: <abc@example.com>\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Bob,\r\n\r\n"
        "Attached are the audit findings for Q3. The control gap in "
        "purchase-order approvals has been resolved.\r\n\r\n"
        "— Alice\r\n"
    )
    return out
