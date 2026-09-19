"""Tests for the API key auth middleware."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from firm_bot.security.api_key import (
    APIKeyAuthMiddleware,
    constant_time_eq,
    hash_key,
    key_from_headers,
)

# ---- pure-function tests ----


def test_constant_time_eq_true_for_same_value() -> None:
    assert constant_time_eq("abc", "abc") is True


def test_constant_time_eq_false_for_different_value() -> None:
    assert constant_time_eq("abc", "abd") is False


def test_constant_time_eq_false_for_different_length() -> None:
    assert constant_time_eq("abc", "abcd") is False


def test_hash_key_is_stable_and_short() -> None:
    """The key hash is used in log lines, so it should be short and stable."""
    h1 = hash_key("my-key")
    h2 = hash_key("my-key")
    assert h1 == h2
    assert len(h1) == 12
    assert hash_key("my-key") != hash_key("other-key")


def _scope_with_headers(headers: list[tuple[str, str]]) -> dict[str, Any]:
    """Build a minimal ASGI http scope with the given header list."""
    return {
        "type": "http",
        "method": "GET",
        "path": "/v1/firms",
        "headers": [(k.lower().encode("latin-1"), v.encode("utf-8")) for k, v in headers],
    }


def test_key_from_headers_bearer() -> None:
    scope = _scope_with_headers([("Authorization", "Bearer secret-key-1")])
    assert key_from_headers(scope) == "secret-key-1"


def test_key_from_headers_bearer_case_insensitive_scheme() -> None:
    scope = _scope_with_headers([("Authorization", "bearer secret-key-1")])
    assert key_from_headers(scope) == "secret-key-1"


def test_key_from_headers_x_api_key() -> None:
    scope = _scope_with_headers([("X-API-Key", "another-key")])
    assert key_from_headers(scope) == "another-key"


def test_key_from_headers_no_header() -> None:
    scope = _scope_with_headers([])
    assert key_from_headers(scope) is None


def test_key_from_headers_bearer_preferred() -> None:
    """If both are present, Authorization: Bearer wins (checked first)."""
    scope = _scope_with_headers(
        [
            ("X-API-Key", "from-x-header"),
            ("Authorization", "Bearer from-auth"),
        ]
    )
    assert key_from_headers(scope) == "from-auth"


def test_key_from_headers_non_bearer_authorization() -> None:
    """If Authorization isn't Bearer, fall through to X-API-Key."""
    scope = _scope_with_headers(
        [
            ("Authorization", "Basic dXNlcjpwYXNz"),
            ("X-API-Key", "from-x-header"),
        ]
    )
    assert key_from_headers(scope) == "from-x-header"


# ---- middleware tests via direct ASGI invocation ----


class _CaptureApp:
    """Minimal ASGI app that records whether the request reached it."""

    def __init__(self) -> None:
        self.reached = False

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        self.reached = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})


def _collect_response(middleware: APIKeyAuthMiddleware, scope: dict[str, Any]) -> tuple[int, bytes]:
    """Drive the middleware manually and capture (status, body)."""
    captured: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict[str, Any]) -> None:
        captured.append(msg)

    async def run() -> None:
        await middleware(scope, receive, send)
        # If middleware passed through to the app, the app also calls send;
        # otherwise the middleware emits 401/403 itself.

    asyncio.run(run())
    if not captured:
        return (0, b"")
    start = next(m for m in captured if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in captured if m["type"] == "http.response.body")
    return (int(start["status"]), body)


def test_middleware_passes_through_when_disabled() -> None:
    """``enabled=False`` means even wrong keys pass through (off by default)."""
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["right"], enabled=False)
    scope = _scope_with_headers([("Authorization", "Bearer wrong")])
    code, _ = _collect_response(mw, scope)
    assert code == 200
    assert capture.reached is True


def test_middleware_allows_valid_bearer() -> None:
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["right-key"])
    scope = _scope_with_headers([("Authorization", "Bearer right-key")])
    code, _ = _collect_response(mw, scope)
    assert code == 200
    assert capture.reached is True


def test_middleware_allows_valid_x_api_key() -> None:
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["right-key"])
    scope = _scope_with_headers([("X-API-Key", "right-key")])
    code, _ = _collect_response(mw, scope)
    assert code == 200
    assert capture.reached is True


def test_middleware_rejects_missing_key_with_401() -> None:
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["right-key"])
    scope = _scope_with_headers([])
    code, body = _collect_response(mw, scope)
    assert code == 401
    assert b"missing" in body.lower()
    assert capture.reached is False


def test_middleware_rejects_wrong_key_with_403() -> None:
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["right-key"])
    scope = _scope_with_headers([("Authorization", "Bearer wrong-key")])
    code, body = _collect_response(mw, scope)
    assert code == 403
    assert b"invalid" in body.lower()
    assert capture.reached is False


def test_middleware_exempts_healthz() -> None:
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["right-key"])
    scope = _scope_with_headers([])
    scope["path"] = "/healthz"
    code, _ = _collect_response(mw, scope)
    assert code == 200
    assert capture.reached is True


def test_middleware_exempts_metrics() -> None:
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["right-key"])
    scope = _scope_with_headers([])
    scope["path"] = "/metrics"
    code, _ = _collect_response(mw, scope)
    assert code == 200
    assert capture.reached is True


def test_middleware_exempts_index_html() -> None:
    """The chat UI at GET / should not require an API key — auth it
    separately at the reverse proxy if you expose it to the public."""
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["right-key"])
    scope = _scope_with_headers([])
    scope["path"] = "/"
    code, _ = _collect_response(mw, scope)
    assert code == 200
    assert capture.reached is True


def test_middleware_gates_v1_endpoints() -> None:
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["right-key"])
    for path in ("/v1/firms", "/v1/firms/demo/config", "/v1/firms/demo/query"):
        scope = _scope_with_headers([])
        scope["path"] = path
        code, _ = _collect_response(mw, scope)
        assert code == 401, f"{path} should require auth"


def test_middleware_accepts_multiple_keys() -> None:
    """Several valid keys configured → caller can present any of them."""
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["k1", "k2", "k3"])
    for key in ("k1", "k2", "k3"):
        scope = _scope_with_headers([("X-API-Key", key)])
        code, _ = _collect_response(mw, scope)
        assert code == 200, f"key {key} should be valid"


def test_middleware_no_keys_configured_rejects_everything() -> None:
    """Defensive: enabled=True but no keys means no one can pass.

    This shouldn't normally happen (the wiring only enables the
    middleware when keys are configured), but if it does we fail
    closed rather than fail open.
    """
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=[], enabled=True)
    scope = _scope_with_headers([("Authorization", "Bearer anything")])
    code, _ = _collect_response(mw, scope)
    assert code == 403
    assert capture.reached is False


# ---- rejection response shape (machine-readable JSON) ----


def test_middleware_rejection_response_is_json() -> None:
    capture = _CaptureApp()
    mw = APIKeyAuthMiddleware(capture, valid_keys=["right"])
    scope = _scope_with_headers([])
    code, body = _collect_response(mw, scope)
    assert code == 401
    parsed = json.loads(body)
    assert parsed["error"] == "unauthorized"
    assert "reason" in parsed
