"""FastAPI middleware that wires metrics, structured logs, and request ids.

:class:`ObservabilityMiddleware` is the runtime glue between the three
other observability modules:

- generates a UUIDv4 request id per request and exposes it via
  ``request.state.request_id`` and the ``X-Request-ID`` response header;
- records the request to the ``firmbot_query_requests`` counter and
  ``firmbot_query_latency_seconds`` histogram when a firm slug is
  present in the URL path;
- sets the :data:`current_request_id` contextvar so log records emitted
  during the request carry the ``"request_id"`` field;
- catches unhandled exceptions, logs them with ``exc_info=True``, and
  returns a JSON ``500`` body rather than the default HTML error page.

Install with ``app.add_middleware(ObservabilityMiddleware)`` after
the FastAPI app is created.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .metrics import query_latency_seconds, query_requests
from .timing import current_request_id

log = logging.getLogger("firm_bot.observability.middleware")

#: Matches ``/v1/firms/{slug}/...`` paths. We deliberately anchor the
#: firm segment so paths like ``/v1/firms`` (no slug) don't accidentally
#: claim an empty firm label.
_FIRM_PATH_RE = re.compile(r"^/v1/firms/([^/]+)(?:/|$)")


def _extract_firm(path: str) -> str | None:
    """Return the firm slug embedded in the request path, if any."""
    match = _FIRM_PATH_RE.match(path)
    return match.group(1) if match else None


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Per-request metrics + structured-log context.

    The middleware is intentionally side-effect-safe: it never raises
    into the request pipeline. If the Prometheus client itself errors
    out (e.g. the registry was unregistered mid-run) we log the failure
    and let the request continue — observability must never be the
    reason a user-facing endpoint returns 5xx.
    """

    #: Maximum length for a client-supplied X-Request-ID header.
    #: UUIDv4 is 36 chars; we accept up to 128 to allow custom ID
    #: formats from upstream proxies / load balancers but reject
    #: anything that looks like header smuggling (CR / LF, semi-
    #: colons, or grossly oversized payloads).
    _MAX_REQUEST_ID_LEN = 128
    #: Allowed charset for client-supplied X-Request-ID. Anything
    #: outside this is rejected (replaced with a server-generated ID
    #: rather than 400ing the request — observability should not
    #: gate user flows).
    _REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Honor client-supplied X-Request-ID if it's well-formed.
        # This makes distributed tracing across services work: the
        # upstream proxy's ID flows through to our audit log. If the
        # header is missing / malformed / oversized we generate our
        # own — observability should never gate user flows.
        incoming = request.headers.get("x-request-id") or request.headers.get("X-Request-ID")
        if (
            incoming
            and len(incoming) <= self._MAX_REQUEST_ID_LEN
            and self._REQUEST_ID_RE.match(incoming)
        ):
            request_id = incoming
        else:
            request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        token = current_request_id.set(request_id)

        start = time.perf_counter()
        firm = _extract_firm(request.url.path)
        # Log on the way in. The ``extra`` dict carries structured
        # fields the JSON formatter will merge into the payload —
        # including the firm label and the HTTP method.
        log.info(
            "request received",
            extra={
                "method": request.method,
                "path": request.url.path,
                "firm": firm,
            },
        )

        try:
            response = await call_next(request)
        except Exception:
            elapsed = time.perf_counter() - start
            # ``exc_info=True`` triggers JsonFormatter to render the
            # traceback into the ``exc_info`` JSON field. We still
            # increment the counter so the failure rate shows up in
            # dashboards.
            log.exception(
                "unhandled exception",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "firm": firm,
                    "elapsed_s": round(elapsed, 6),
                },
            )
            if firm is not None:
                try:
                    query_requests.labels(firm=firm, status="500").inc()
                    query_latency_seconds.labels(firm=firm).observe(elapsed)
                except Exception:  # pragma: no cover - defensive
                    log.exception("failed to record metrics on error path")
            current_request_id.reset(token)
            return JSONResponse(
                {"error": "internal_server_error", "request_id": request_id},
                status_code=500,
                headers={"X-Request-ID": request_id},
            )

        elapsed = time.perf_counter() - start

        if firm is not None:
            try:
                query_requests.labels(firm=firm, status=str(response.status_code)).inc()
                query_latency_seconds.labels(firm=firm).observe(elapsed)
            except Exception:  # pragma: no cover - defensive
                log.exception("failed to record per-request metrics")

        response.headers["X-Request-ID"] = request_id

        log.info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "firm": firm,
                "status_code": response.status_code,
                "elapsed_s": round(elapsed, 6),
            },
        )

        current_request_id.reset(token)
        return response


__all__ = ["ObservabilityMiddleware"]
