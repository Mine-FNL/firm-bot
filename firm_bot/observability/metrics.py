"""Prometheus metric registry for firm-bot.

All collectors are bound to a private :class:`CollectorRegistry` rather
than the global default. This keeps tests isolated (one test's
``firmbot_query_requests_total`` observations don't bleed into the next
test) and keeps multi-tenant deployments of firm-bot from polluting a
host process's metrics when imported as a library.

Metric naming follows the Prometheus convention:

    firmbot_<subsystem>_<name>_<unit>

Units are spelled out (``_seconds``, ``_total``). Labels are bounded
cardinality sets (``firm``, ``status``, ``source_type``, ``stage``).

The text exposition format is rendered by :func:`metrics_response`,
which is the intended body of a ``GET /metrics`` endpoint.
"""

from __future__ import annotations

from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# A dedicated registry. Tests use a per-test isolated registry so the
# counters don't accumulate state across tests; production code uses
# this module-level singleton.
REGISTRY = CollectorRegistry()

# ---- /query --------------------------------------------------------------

query_requests = Counter(
    "firmbot_query_requests",
    "Total /query requests",
    labelnames=("firm", "status"),
    registry=REGISTRY,
)

query_latency_seconds = Histogram(
    "firmbot_query_latency_seconds",
    "End-to-end /query latency in seconds",
    labelnames=("firm",),
    # Tuned for local LLM workloads: a 7B model on an M4 produces a
    # token in ~50 ms; a 200-token answer therefore lands around 10 s.
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)

# ---- per-stage -----------------------------------------------------------
# Stages: embed, retrieve, rerank, answer, guard. Embedding and rerank
# may be skipped depending on configuration — that is observable as a
# missing label value, not as an error.

stage_latency_seconds = Histogram(
    "firmbot_stage_latency_seconds",
    "Per-stage latency in seconds",
    labelnames=("stage",),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
    registry=REGISTRY,
)

# ---- ingest --------------------------------------------------------------
# source_type values: pdf, eml, docx, txt. New extractors should add
# their own label value rather than overload an existing one.

ingest_chunks = Counter(
    "firmbot_ingest_chunks",
    "Total chunks ingested",
    labelnames=("firm", "source_type"),
    registry=REGISTRY,
)

# ---- gauge ---------------------------------------------------------------

active_firms = Gauge(
    "firmbot_active_firms",
    "Number of configured firms",
    registry=REGISTRY,
)


def metrics_response() -> Response:
    """Return a FastAPI Response with the Prometheus text exposition body.

    The content type is the canonical ``text/plain; version=0.0.4``
    media type from :data:`prometheus_client.CONTENT_TYPE_LATEST`. The
    body is ``generate_latest(REGISTRY)`` rendered as bytes; FastAPI
    will set ``Content-Length`` automatically.
    """
    body = generate_latest(REGISTRY)
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)
