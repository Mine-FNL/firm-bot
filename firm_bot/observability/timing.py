"""Per-stage timing primitives.

:func:`stage_timing` is a context manager that records its wall-clock
duration to the ``firmbot_stage_latency_seconds`` Prometheus histogram.
Wrap each major pipeline stage (embed, retrieve, rerank, answer, guard)
to get end-to-end and per-stage SLOs out of the box:

.. code-block:: python

    with stage_timing("retrieve"):
        hits = hybrid_search(...)

The context manager also sets the :data:`current_stage` contextvar so
that structured log records emitted inside the block carry a ``"stage"``
field. This is what makes a JSON log line say
``"stage": "retrieve"`` next to the timestamp without manual plumbing.

The contextvar approach is asyncio-safe: :class:`contextvars.ContextVar`
snapshots propagate across ``await`` boundaries, so even code that
yields to the event loop keeps the stage label attached.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .metrics import stage_latency_seconds

log = logging.getLogger("firm_bot.observability.timing")

#: Holds the request id set by :class:`ObservabilityMiddleware`. JSON
#: log records emitted while this is set include a ``"request_id"`` key.
current_request_id: ContextVar[str | None] = ContextVar(
    "firm_bot_request_id", default=None
)

#: Holds the name of the pipeline stage currently in scope. JSON log
#: records emitted while this is set include a ``"stage"`` key.
current_stage: ContextVar[str | None] = ContextVar("firm_bot_stage", default=None)


@contextmanager
def stage_timing(stage: str) -> Iterator[None]:
    """Measure a pipeline stage and emit one histogram observation.

    The elapsed wall-clock time (``time.perf_counter``) is recorded to
    :data:`firm_bot.observability.metrics.stage_latency_seconds` with
    the given ``stage`` label. Exceptions inside the block still record
    the observation — partial latency on failure is operationally
    useful — and are then re-raised.

    The stage name is also exposed via the :data:`current_stage`
    contextvar for the duration of the block so log records carry it.
    """
    start = time.perf_counter()
    token = current_stage.set(stage)
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        try:
            stage_latency_seconds.labels(stage=stage).observe(elapsed)
        except Exception:  # pragma: no cover - defensive: metrics must never raise
            log.exception("failed to record stage_timing observation")
        current_stage.reset(token)


@contextmanager
def stage_timer(stage: str) -> Iterator[dict[str, float]]:
    """Like :func:`stage_timing` but also exposes elapsed_ms to the caller.

    Yields a single-key dict ``{"elapsed_ms": 0.0}`` which is populated
    when the ``with`` block exits. Use this when you need the duration
    for a non-Prometheus consumer (audit log, response payload, debug
    print) **and** still want the histogram observation.

    Example::

        with stage_timer("answer") as t:
            text = answer_with_ollama(...)
        answer_ms = t["elapsed_ms"]

    Note: the dict is the same object yielded to the body, so writing
    to it from inside the block is supported. The canonical pattern is
    to read after the block exits.
    """
    out: dict[str, float] = {"elapsed_ms": 0.0}
    start = time.perf_counter()
    with stage_timing(stage):
        yield out
    out["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 2)
