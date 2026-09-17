"""Production hardening for firm-bot's HTTP surface.

Public API
----------

- :class:`TokenBucket`, :class:`RateLimiter` — leaky-bucket-per-key
  rate limiting for ASGI scopes (rate_limit.py).
- :class:`SecurityMiddleware` — ASGI middleware that wraps a FastAPI /
  Starlette app to enforce rate limit, body size, and CORS (middleware.py).
- :class:`RedactFilter` — logging filter that scrubs known secret patterns
  from log records before emission (redact.py).

Design constraints
------------------

- Single-process. The token bucket map is in-memory; multi-worker
  deployments need a shared store (Redis). See SECURITY.md for guidance.
- Synchronous core. The middleware is ASGI (async) but rate limiting
  uses ``threading.Lock`` rather than asyncio primitives so it stays
  compatible with any ASGI worker shape.
- Dependency direction. We do not import from :mod:`firm_bot.redact`
  (PII redaction at ingest) — log redaction is a separate concern with
  its own patterns, so they share regex constants rather than Python
  imports.
"""
from __future__ import annotations

from .middleware import SecurityMiddleware
from .rate_limit import RateLimiter, TokenBucket
from .redact import RedactFilter

__all__ = ["RateLimiter", "RedactFilter", "SecurityMiddleware", "TokenBucket"]
