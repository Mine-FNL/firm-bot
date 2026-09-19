"""Observability primitives for firm-bot.

This package provides three orthogonal surfaces:

1. **Prometheus metrics** (:mod:`firm_bot.observability.metrics`)
   Counters, histograms, and gauges exported via ``/metrics``. Use
   :func:`metrics_response` to render the Prometheus text exposition.

2. **Structured JSON logs** (:mod:`firm_bot.observability.logging_config`)
   A :class:`logging.Formatter` subclass that emits one JSON object per
   record. :func:`setup_logging` installs it on the root logger.

3. **Per-stage timing** (:mod:`firm_bot.observability.timing`)
   :func:`stage_timing` is a context manager that records elapsed seconds
   to the ``firmbot_stage_latency_seconds`` histogram with the stage
   name as a label.

4. **Request middleware** (:mod:`firm_bot.observability.middleware`)
   :class:`ObservabilityMiddleware` wires all three surfaces into a
   FastAPI app: it generates a request id, observes request latency,
   records the per-firm counter, and ensures unhandled exceptions are
   logged with full traceback.

Activation is opt-in: import :func:`setup_logging` at process start and
add ``app.add_middleware(ObservabilityMiddleware)`` to your FastAPI app.
The optional ``prometheus_client`` dependency is installed via
``pip install firm-bot[observability]``.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST

from .logging_config import JsonFormatter, setup_logging
from .metrics import (
    REGISTRY,
    active_firms,
    ingest_chunks,
    metrics_response,
    query_latency_seconds,
    query_requests,
    stage_latency_seconds,
)
from .middleware import ObservabilityMiddleware
from .timing import current_request_id, current_stage, stage_timer, stage_timing

__all__ = [
    "CONTENT_TYPE_LATEST",
    "REGISTRY",
    "JsonFormatter",
    "ObservabilityMiddleware",
    "active_firms",
    "current_request_id",
    "current_stage",
    "ingest_chunks",
    "metrics_response",
    "query_latency_seconds",
    "query_requests",
    "setup_logging",
    "stage_latency_seconds",
    "stage_timer",
    "stage_timing",
]
