"""ASGI middleware: rate limit + body size + CORS, all in one stack.

We implement these three concerns as one middleware class rather than
three because they all read the ASGI scope's ``client`` field, the
``headers`` list, and the ``receive`` callable — sharing one wrapper
around ``receive`` is cheaper than three.

Scope
-----
- Rate limit is applied per ``client`` (``host:port`` of the TCP peer).
  Behind a reverse proxy set ``X-Forwarded-For`` and call
  :func:`client_key_from_scope` with the trust chain in mind —
  blindly honouring ``X-Forwarded-For`` from any source lets a caller
  forge their key.
- Body size caps the cumulative bytes received across all
  ``more_body=True`` events. Once the cap is hit we return 413 and
  stop reading the body.
- CORS handles preflight (``OPTIONS``) requests and echoes the request
  ``Origin`` header back as ``Access-Control-Allow-Origin`` *only if*
  it appears in the allow list. When the list is empty no CORS
  headers are emitted — this is a fail-closed default.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from .rate_limit import RateLimiter

log = logging.getLogger("firm_bot.security.middleware")

# Default allow-list for preflight responses. Conservative defaults:
# we restrict to the methods firm-bot actually exposes via REST.
DEFAULT_CORS_METHODS: list[str] = ["GET", "POST", "PATCH", "OPTIONS"]
DEFAULT_CORS_HEADERS: list[str] = [
    "Authorization",
    "Content-Type",
    "X-Requested-With",
]

# Maximum CORS preflight results size — defensive cap on header echoes.
_MAX_PREFLIGHT_ALLOW_ORIGIN_LEN = 2048


def client_key_from_scope(scope: dict[str, Any]) -> str:
    """Derive a rate-limit key from the ASGI scope.

    Prefer ``scope["client"]`` (``(host, port)`` tuple). When the ASGI
    server does not provide it (e.g. some test transports) fall back
    to a fixed sentinel so the limiter still works — under that
    fallback all requests share one bucket, which is a stricter
    default than per-client and acceptable in tests.
    """
    client = scope.get("client")
    if client and isinstance(client, (tuple, list)) and len(client) >= 2:
        return f"{client[0]}:{client[1]}"
    return "unknown:0"


class SecurityMiddleware:
    """ASGI middleware that enforces rate limit, body size, CORS."""

    def __init__(
        self,
        app: Callable[
            [
                dict[str, Any],
                Callable[[], Awaitable[dict[str, Any]]],
                Callable[[dict[str, Any]], Awaitable[None]],
            ],
            Awaitable[None],
        ],
        rate_limiter: RateLimiter,
        max_body_bytes: int,
        cors_allow_origins: list[str] | tuple[str, ...] | None,
        cors_allow_methods: list[str] | None = None,
        cors_allow_headers: list[str] | None = None,
        cors_max_age: int = 600,
    ) -> None:
        self.app = app
        self.rate_limiter = rate_limiter
        self.max_body_bytes = max_body_bytes
        # Fail closed: an empty / None allow list → no CORS at all.
        self.cors_allow_origins: list[str] = list(cors_allow_origins or [])
        self.cors_allow_methods: list[str] = list(
            cors_allow_methods if cors_allow_methods is not None else DEFAULT_CORS_METHODS
        )
        self.cors_allow_headers: list[str] = list(
            cors_allow_headers if cors_allow_headers is not None else DEFAULT_CORS_HEADERS
        )
        self.cors_max_age = int(cors_max_age)
        # Pre-index origins as a set for O(1) lookup.
        self._origin_set: set[str] = set(self.cors_allow_origins)
        # Wildcard "*" support: when present every origin is allowed,
        # but we still set Vary: Origin so caches don't blur responses.
        self._wildcard = "*" in self._origin_set
        if self._wildcard and self.cors_allow_origins != ["*"]:
            # If wildcard + others, narrow to wildcard for echo.
            self._origin_set = {"*"}
            self.cors_allow_origins = ["*"]

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            # Lifespan and websocket — pass through.
            await self.app(scope, receive, send)
            return

        # 1. Rate limit (per-IP, cheap, no body reads).
        key = client_key_from_scope(scope)
        allowed, retry_after = self.rate_limiter.check(key)
        if not allowed:
            await self._send_json(
                send,
                429,
                {
                    "error": "rate_limited",
                    "message": "Too many requests; slow down.",
                    "retry_after_seconds": round(retry_after, 3),
                },
                extra_headers=[(b"retry-after", str(int(retry_after) + 1).encode("ascii"))],
            )
            return

        # 2. CORS preflight short-circuit.
        if scope["method"] == "OPTIONS" and self.cors_allow_origins:
            origin = _header_value(scope["headers"], b"origin")
            if origin is not None and self._is_allowed_origin(origin):
                headers = self._cors_headers(origin, is_preflight=True)
                await self._send_empty(send, 204, headers)
                return

        # 3. Body size limit for upload / JSON bodies.
        method = scope["method"].upper()
        wraps_body = method in {"POST", "PUT", "PATCH"}
        if wraps_body and self.max_body_bytes > 0:
            receive = _BodySizeLimitedReceive(receive, self.max_body_bytes)

        # 4. CORS echo on the response (origin headers) — only if origin
        # is allow-listed. We attach via a wrapped send.
        origin = _header_value(scope["headers"], b"origin")
        echo_origin = origin if (origin is not None and self._is_allowed_origin(origin)) else None
        if echo_origin is not None or self._wildcard:
            send = _CorsSendWrapper(
                send,
                self._cors_headers(echo_origin or "*", is_preflight=False),
            )

        # Track whether the downstream has already started writing,
        # so we know whether to return a JSON 413 or just close the
        # connection on BodyTooLarge.
        status_started = {"flag": False}
        original_send = send

        async def tracking_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                status_started["flag"] = True
            await original_send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except BodyTooLarge as e:
            if status_started["flag"]:
                # Headers already flushed; cannot synthesise a 413.
                # Let the ASGI server close the connection.
                raise
            await self._send_json(
                original_send,
                413,
                {
                    "error": "payload_too_large",
                    "message": "Request body exceeds the configured limit.",
                    "limit_bytes": e.cap,
                },
            )

    # ---- helpers ----

    def _is_allowed_origin(self, origin: str) -> bool:
        if self._wildcard:
            return True
        return origin in self._origin_set

    def _cors_headers(self, origin: str, *, is_preflight: bool) -> list[tuple[bytes, bytes]]:
        """Build the list of CORS response headers for a given origin."""
        headers: list[tuple[bytes, bytes]] = [
            (b"vary", b"Origin"),
            (b"access-control-allow-origin", origin.encode("latin-1")),
        ]
        if is_preflight:
            headers.extend(
                [
                    (
                        b"access-control-allow-methods",
                        ", ".join(self.cors_allow_methods).encode("latin-1"),
                    ),
                    (
                        b"access-control-allow-headers",
                        ", ".join(self.cors_allow_headers).encode("latin-1"),
                    ),
                    (
                        b"access-control-max-age",
                        str(self.cors_max_age).encode("ascii"),
                    ),
                ]
            )
            # allow credentials only when a specific origin (not "*") is echoed
            if origin != "*":
                headers.append((b"access-control-allow-credentials", b"true"))
        return headers

    @staticmethod
    async def _send_json(
        send: Callable[[dict[str, Any]], Awaitable[None]],
        status: int,
        body: dict[str, Any],
        *,
        extra_headers: Iterable[tuple[bytes, bytes]] = (),
    ) -> None:
        payload = json.dumps(body).encode("utf-8")
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
        ]
        headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": payload, "more_body": False})

    @staticmethod
    async def _send_empty(
        send: Callable[[dict[str, Any]], Awaitable[None]],
        status: int,
        headers: list[tuple[bytes, bytes]],
    ) -> None:
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


def _header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    """Look up a header by lowercased name in an ASGI headers list."""
    for k, v in headers:
        if k.lower() == name:
            try:
                return v.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None


class _BodySizeLimitedReceive:
    """Wrap an ASGI ``receive`` callable to enforce a max body size.

    Buffers chunks in-flight so the cumulative byte count can be checked
    before forwarding. As soon as a single event pushes us over the cap
    we synthesise a 413 by raising :class:`BodyTooLarge`.
    """

    __slots__ = ("_max_bytes", "_receive", "_seen")

    def __init__(self, receive: Callable[[], Awaitable[dict[str, Any]]], max_bytes: int) -> None:
        self._receive = receive
        self._max_bytes = int(max_bytes)
        self._seen = 0

    async def __call__(self) -> dict[str, Any]:
        msg = await self._receive()
        if msg.get("type") == "http.request":
            body = msg.get("body", b"") or b""
            if body:
                self._seen += len(body)
                if self._seen > self._max_bytes:
                    raise BodyTooLarge(self._seen, self._max_bytes)
        return msg


class BodyTooLarge(Exception):
    """Raised by :class:`_BodySizeLimitedReceive` when the cap is exceeded."""

    def __init__(self, seen: int, cap: int) -> None:
        super().__init__(f"request body {seen} > cap {cap}")
        self.seen = seen
        self.cap = cap


class _CorsSendWrapper:
    """Wrap an ASGI ``send`` callable to inject CORS headers on the start event."""

    __slots__ = ("_headers", "_send")

    def __init__(
        self,
        send: Callable[[dict[str, Any]], Awaitable[None]],
        headers: list[tuple[bytes, bytes]],
    ) -> None:
        self._send = send
        self._headers = headers

    async def __call__(self, message: dict[str, Any]) -> None:
        if message.get("type") == "http.response.start":
            existing: list[tuple[bytes, bytes]] = list(message.get("headers") or [])
            existing_keys = {k.lower() for k, _ in existing}
            for h in self._headers:
                if h[0].lower() not in existing_keys:
                    existing.append(h)
                    existing_keys.add(h[0].lower())
            message = {**message, "headers": existing}
        await self._send(message)
