"""API key authentication for firm-bot.

Opt-in: enabled when ``FIRM_BOT_REQUIRE_API_KEY=1`` AND at least one
key is configured (via ``FIRM_BOT_API_KEYS`` env var or
``api_keys`` config field). Default off — single-tenant deployments
behind a reverse proxy doing auth don't need it.

Key lookup order:
  1. ``Authorization: Bearer <key>`` header
  2. ``X-API-Key: <key>`` header

Endpoints exempt by default:
  - ``GET /healthz``   (load-balancer probes)
  - ``GET /metrics``    (Prometheus scrapes)
  - ``GET /``           (the HTML chat UI; protect separately if needed)

Configuration
-------------
  FIRM_BOT_REQUIRE_API_KEY=1        # enable the check
  FIRM_BOT_API_KEYS=key1,key2,...   # comma-separated valid keys

The key space is treated as opaque — there's no rotation, expiry, or
per-user identity. For real per-user auth, deploy behind
oauth2-proxy / Pomerium / Cloudflare Access / your reverse proxy of
choice. This module only provides a single shared-secret gate.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger("firm_bot.security.api_key")


def constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string comparison (avoids timing-based key recovery)."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def key_from_headers(scope: dict[str, Any]) -> str | None:
    """Extract the API key from the ASGI scope headers.

    Returns the key string or ``None`` if no recognised header is
    present. Case-insensitive header name matching per RFC 7230.
    """
    # ASGI headers are list[tuple[bytes, bytes]] in raw form. Most
    # frameworks normalise to bytes lowercase.
    raw = scope.get("headers") or []
    auth_value: bytes | None = None
    x_api_key_value: bytes | None = None
    for name, value in raw:
        n = name.decode("latin-1").lower() if isinstance(name, bytes) else name.lower()
        v = value if isinstance(value, bytes) else value.encode("utf-8")
        if n == "authorization":
            auth_value = v
        elif n == "x-api-key":
            x_api_key_value = v
    if auth_value:
        # "Bearer <key>" — case-insensitive scheme per RFC 6750
        text = auth_value.decode("latin-1")
        parts = text.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    if x_api_key_value:
        return x_api_key_value.decode("utf-8").strip()
    return None


def hash_key(key: str) -> str:
    """SHA-256 hex of a key — used so we never log the key in cleartext.

    Not used for storage (we hold keys in plaintext in config — the
    security boundary is "who can read config.yaml"). Used only in
    log lines and access-log records.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


class APIKeyAuthMiddleware:
    """ASGI middleware that gates ``/v1/*`` on a valid API key.

    Exempt paths (the health/metrics/UI surface) are passed through
    untouched. Everything else is rejected with 401 if the key is
    missing or 403 if it doesn't match.

    Why two status codes:
      - 401 = "you didn't try" — caller should add the header
      - 403 = "you tried but your key is wrong" — caller is asking
        with the wrong credentials
    """

    EXEMPT_PATHS: frozenset[str] = frozenset({"/", "/healthz", "/metrics"})

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
        valid_keys: list[str],
        enabled: bool = True,
    ) -> None:
        self.app = app
        self.enabled = enabled
        # Always store the hashed form so the comparison below uses a
        # fixed-length token. This doesn't make a hash stronger — but
        # it does stop log lines from leaking key lengths when we
        # eventually log which key was used.
        self._key_hashes: set[str] = {hash_key(k) for k in valid_keys}

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if not self.enabled or scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        presented = key_from_headers(scope)
        if presented is None:
            await self._reject(send, status=401, reason="missing api key")
            return

        if hash_key(presented) not in self._key_hashes:
            # Don't include the key in the log line — just note the failure.
            log.warning("api key rejected for %s", path)
            await self._reject(send, status=403, reason="invalid api key")
            return

        await self.app(scope, receive, send)

    async def _reject(
        self,
        send: Callable[[dict[str, Any]], Awaitable[None]],
        status: int,
        reason: str,
    ) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        body = ('{"error": "unauthorized", "reason": "' + reason + '"}').encode("utf-8")
        await send({"type": "http.response.body", "body": body, "more_body": False})
