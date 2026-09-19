"""Public API for ``firm-bot-sdk``.

Importing the package gives you the :class:`FirmBotClient` plus the
full error and dataclass hierarchy. The module is dependency-free at
runtime — only stdlib is required.

Typical usage:

    >>> from firm_bot_sdk import FirmBotClient, NotFoundError
    >>> client = FirmBotClient("http://localhost:8080", api_key="fb_...")
    >>> try:
    ...     cfg = client.get_firm("acme-llp")
    ... except NotFoundError as e:
    ...     print("no such firm:", e.path)
"""

from __future__ import annotations

from .client import FirmBotClient
from .errors import (
    AuthError,
    FirmBotError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from .types import (
    AuditLogEntry,
    EvalResult,
    FirmConfig,
    FirmSummary,
    IngestResult,
    QueryHit,
    QueryIssue,
    QueryResponse,
    UploadResult,
)

__all__ = [
    "AuditLogEntry",
    "AuthError",
    "EvalResult",
    "FirmBotClient",
    "FirmBotError",
    "FirmConfig",
    "FirmSummary",
    "IngestResult",
    "NotFoundError",
    "QueryHit",
    "QueryIssue",
    "QueryResponse",
    "RateLimitError",
    "ServerError",
    "UploadResult",
    "ValidationError",
]
