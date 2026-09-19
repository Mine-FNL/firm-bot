"""Exception hierarchy for the firm-bot SDK.

All exceptions derive from :class:`FirmBotError`, which itself derives
from :class:`Exception`. The HTTP-status -> exception mapping is:

    401, 403 -> :class:`AuthError`
    404      -> :class:`NotFoundError`
    400, 422 -> :class:`ValidationError`
    429      -> :class:`RateLimitError`
    5xx      -> :class:`ServerError`

Network-level failures (DNS, connection refused, read timeout) raise
:class:`FirmBotError` with the underlying :class:`urllib.error.URLError`
chained via ``__cause__``. The client never lets a raw urllib exception
escape — they are always normalised into the SDK's hierarchy so that
calling code can use a single ``except FirmBotError`` block.
"""

from __future__ import annotations

from typing import Any


class FirmBotError(Exception):
    """Base class for every error raised by :class:`FirmBotClient`.

    Carries the original HTTP status (when applicable), the response
    body parsed as JSON-or-string, and the request path so callers can
    log or surface a useful diagnostic.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: Any = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status: int | None = status
        self.body: Any = body
        self.path: str | None = path

    def __str__(self) -> str:
        bits = [super().__str__()]
        if self.status is not None:
            bits.insert(0, f"[{self.status}]")
        if self.path is not None:
            bits.append(f"path={self.path}")
        return " ".join(bits)


class AuthError(FirmBotError):
    """401 Unauthorized or 403 Forbidden."""


class NotFoundError(FirmBotError):
    """404 Not Found — typically a missing firm slug."""


class ValidationError(FirmBotError):
    """400 Bad Request or 422 Unprocessable Entity."""


class RateLimitError(FirmBotError):
    """429 Too Many Requests."""


class ServerError(FirmBotError):
    """Any 5xx response from the server."""
