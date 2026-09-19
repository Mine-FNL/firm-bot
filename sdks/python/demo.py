"""10-line demo of the firm-bot SDK against a mock server.

Run it from this directory:

    python demo.py

It installs a fake transport that replays canned firm-bot responses,
so the demo opens no sockets and never touches a real server.
"""

from __future__ import annotations

import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent / "src"))

from firm_bot_sdk import FirmBotClient, QueryResponse


def make_fake_transport() -> Any:
    """Programmable stub for :func:`urllib.request.urlopen`."""

    class FakeTransport:
        def __init__(self) -> None:
            self.requests: list[Any] = []
            # Each entry is (status, body_bytes, content_type).
            # Order matches the demo's call sequence:
            # 1) create_firm
            # 2) upload_file (inside ingest)
            # 3) POST /ingest
            # 4) POST /query
            self.responses: list[tuple[int, bytes, str]] = [
                (
                    201,
                    json.dumps(
                        {
                            "slug": "demo",
                            "name": "Demo Firm",
                            "system_prompt": "",
                            "llm_model": "",
                            "contact_email": "",
                            "notes": "",
                        }
                    ).encode(),
                    "application/json",
                ),
                (
                    200,
                    json.dumps({"stored": "/x.pdf", "size_bytes": 11}).encode(),
                    "application/json",
                ),
                (
                    200,
                    json.dumps(
                        {
                            "stats": {"files_total": 1, "files_failed": 0, "files_skipped": 0},
                            "chunks_indexed": 4,
                            "skipped": 0,
                        }
                    ).encode(),
                    "application/json",
                ),
                (
                    200,
                    json.dumps(
                        {
                            "answer": "Indemnification is capped at $1M.",
                            "cited": ["[contract.pdf:p.4]"],
                            "hits": [],
                            "issues": [],
                            "summary": "ok",
                            "confidence": 0.8,
                            "latency_ms": 50.0,
                            "model": "llama3.1",
                            "prompt_injection_suspected": 0,
                            "prompt_injection_patterns": [],
                            "stage_latency_ms": {},
                        }
                    ).encode(),
                    "application/json",
                ),
            ]

        def urlopen(self, req: Any, timeout: float = 0) -> Any:
            self.requests.append(req)
            status, body, _ctype = self.responses.pop(0)

            class _Resp:
                def __init__(self) -> None:
                    self.status = status
                    self._body = body

                def read(self) -> bytes:
                    return self._body

                def __enter__(self) -> _Resp:
                    return self

                def __exit__(self, *a: object) -> None:
                    pass

            if status >= 400:
                raise urllib.error.HTTPError(
                    url="<fake>", code=status, msg=f"HTTP {status}", hdrs={}, fp=None
                )
            return _Resp()

    return FakeTransport()


def main() -> None:
    fake = make_fake_transport()
    urllib.request.urlopen = fake.urlopen  # type: ignore[assignment]
    # 10 lines of actual SDK usage below ---------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        corpus = Path(tmp) / "contract.pdf"
        corpus.write_bytes(b"%PDF-1.4 fake")
        client = FirmBotClient("http://demo.example", api_key="demo-key")
        client.create_firm("demo", "Demo Firm")
        client.ingest("demo", tmp)
        resp: QueryResponse = client.query("demo", "What is the indemnification cap?")
    # -------------------------------------------------------------------------
    print(f"answer: {resp.answer}")
    print(f"confidence: {resp.confidence}")
    print(f"HTTP calls made: {len(fake.requests)}")


if __name__ == "__main__":
    main()
