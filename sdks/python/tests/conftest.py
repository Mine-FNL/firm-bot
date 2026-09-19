"""Shared pytest fixtures for the firm-bot SDK test suite.

The client uses :mod:`urllib.request` directly, so the test suite
patches :func:`urllib.request.urlopen` with a fake transport. The
fake records every call so tests can inspect the request (method,
URL, headers, body) and return canned responses (status code,
headers, body) without ever opening a socket.
"""

from __future__ import annotations

import json
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class CapturedRequest:
    """A single recorded ``urllib.request`` call."""

    method: str
    url: str
    headers: dict[str, str]
    body: bytes


@dataclass
class CannedResponse:
    """One pre-programmed reply for the fake transport."""

    status: int
    body: bytes = b""
    content_type: str = "application/json"


class _FakeResponse:
    """Context-manager-compatible stand-in for ``http.client`` response."""

    def __init__(self, canned: CannedResponse) -> None:
        self.status = canned.status
        self._body = canned.body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeHTTPError(urllib.error.HTTPError):
    """Mirrors :class:`urllib.error.HTTPError` for the fake transport.

    Subclassing the real class — instead of faking an ``Exception`` —
    lets the SDK's ``except urllib.error.HTTPError`` block fire in
    tests, the same way it would against a real server.
    """

    def __init__(self, canned: CannedResponse) -> None:
        # HTTPError.__init__ expects (url, code, msg, hdrs, fp).
        # We don't need a real fp because the SDK only calls .read()
        # which we override below.
        super().__init__(
            url="<fake>",
            code=canned.status,
            msg=f"HTTP Error {canned.status}",
            hdrs={},
            fp=None,
        )
        self._body = canned.body

    def read(self) -> bytes:
        return self._body


@dataclass
class FakeTransport:
    """Programmable fake for ``urllib.request.urlopen``.

    Tests push responses via :meth:`enqueue` (status code, JSON-or-bytes
    body) and inspect recorded requests via :attr:`requests`. If the
    queue runs dry, the fake raises ``AssertionError`` so forgotten
    stubs are loud, not silent.
    """

    requests: list[CapturedRequest] = field(default_factory=list)
    responses: list[CannedResponse] = field(default_factory=list)

    def enqueue(
        self,
        status: int = 200,
        body: Any = None,
        content_type: str | None = None,
    ) -> None:
        if body is None:
            payload = b""
        elif isinstance(body, (bytes, bytearray)):
            payload = bytes(body)
        else:
            payload = json.dumps(body).encode("utf-8")
        if content_type is None:
            content_type = "application/json" if payload else "text/plain"
        self.responses.append(
            CannedResponse(status=status, body=payload, content_type=content_type)
        )

    def urlopen(self, req: Any, timeout: float = 0) -> _FakeResponse:  # type: ignore[override]
        # Capture request details before responding so tests can
        # assert against the URL/headers/body even if the response
        # raises.
        self.requests.append(
            CapturedRequest(
                method=str(req.method),
                url=str(req.full_url),
                headers={k: v for k, v in req.header_items()},
                body=req.data if isinstance(req.data, (bytes, bytearray)) else b"",
            )
        )
        if not self.responses:
            raise AssertionError(
                f"FakeTransport received an unexpected request: {req.method} {req.full_url}"
            )
        canned = self.responses.pop(0)
        if canned.status >= 400:
            raise _FakeHTTPError(canned)
        return _FakeResponse(canned)


@pytest.fixture
def fake_transport(monkeypatch: pytest.MonkeyPatch) -> FakeTransport:
    """Patch ``urllib.request.urlopen`` with a programmable fake."""
    transport = FakeTransport()
    monkeypatch.setattr("urllib.request.urlopen", transport.urlopen)
    return transport


@pytest.fixture
def make_client(fake_transport: FakeTransport) -> Callable[..., Any]:
    """Factory that yields a :class:`FirmBotClient` wired to the fake transport."""
    from firm_bot_sdk import FirmBotClient

    def _factory(
        base_url: str = "https://firm-bot.test",
        api_key: str = "test-key",
        timeout_s: float = 5.0,
    ) -> FirmBotClient:
        return FirmBotClient(base_url=base_url, api_key=api_key, timeout_s=timeout_s)

    return _factory
