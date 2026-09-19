"""Structured JSON logging for firm-bot.

:func:`setup_logging` configures the root logger with a single
:class:`~logging.StreamHandler` whose formatter is :class:`JsonFormatter`.
Every log record becomes one line of newline-delimited JSON, suitable
for ingestion by Loki, Elastic, Datadog, or any structured-log
collector.

The JSON object always carries:

- ``timestamp``  — ISO 8601 UTC, e.g. ``"2026-09-17T10:49:23.412Z"``
- ``level``      — record level name (``INFO``, ``ERROR``, …)
- ``logger``     — the dotted logger name (``firm_bot.api``)
- ``message``    — the formatted message

It conditionally carries:

- ``request_id`` — set by :class:`ObservabilityMiddleware`
- ``stage``      — set by :func:`stage_timing`
- ``exc_info``   — present when ``logger.exception(...)`` is called;
  rendered as the standard-library ``traceback.format_exception`` text

Calling :func:`setup_logging` more than once is safe: it clears
existing handlers on the root logger first, so tests that flip the
level mid-run do not stack handlers.
"""

from __future__ import annotations

import datetime
import json
import logging
import logging.config
import traceback
from typing import Any

from .timing import current_request_id, current_stage

#: Reserved :class:`logging.LogRecord` attributes. Anything outside this
#: set on a record is treated as user-supplied ``extra={...}`` data and
#: merged into the JSON payload. The set is taken from the CPython
#: ``LogRecord`` documentation; adding new stdlib attributes to logging
#: would require updating this constant.
_RESERVED_LOGRECORD_KEYS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Render log records as one JSON object per line.

    The formatter is deliberately dependency-free (stdlib only) and
    refuses to call into anything that might itself log — that would
    cause infinite recursion. Exceptions are rendered with
    :func:`traceback.format_exception`, matching the textual layout
    operators expect from a tail of structured logs.
    """

    def format(self, record: logging.LogRecord) -> str:
        # ``getMessage`` does the ``record.msg % record.args`` step the
        # base ``Formatter`` would do. Calling it ourselves keeps the
        # behaviour identical to a plain text formatter.
        message = record.getMessage()

        # Build the payload in insertion order so the timestamp comes
        # first when pretty-printed. ``default=str`` lets us serialise
        # odd ``extra`` values (datetime, Path, Decimal) without
        # crashing — operators can grep for them downstream.
        payload: dict[str, Any] = {
            "timestamp": _isoformat_utc(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }

        # Context-bound fields. ContextVars default to ``None``, so we
        # only emit the key when a value is set — keeps the steady-state
        # payload small.
        request_id = current_request_id.get()
        if request_id is not None:
            payload["request_id"] = request_id

        stage = current_stage.get()
        if stage is not None:
            payload["stage"] = stage

        # Any ``extra={...}`` keys on the record are merged in. We do
        # this *after* the context fields so a logger that explicitly
        # passes ``extra={"stage": ...}`` wins.
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_KEYS or key.startswith("_"):
                continue
            if key not in payload:
                payload[key] = value

        if record.exc_info:
            # ``format_exception`` joins the traceback into a single
            # multi-line string. Newlines survive ``json.dumps`` because
            # JSON strings allow ``\n`` — log shippers handle that
            # without special-casing.
            payload["exc_info"] = "".join(
                traceback.format_exception(
                    record.exc_info[0], record.exc_info[1], record.exc_info[2]
                )
            )

        if record.stack_info:
            payload["stack_info"] = record.stack_info

        return json.dumps(payload, default=str, ensure_ascii=False)


def _isoformat_utc(epoch_seconds: float) -> str:
    """Format ``time.time()`` as ISO 8601 UTC with millisecond precision.

    Example output: ``"2026-09-17T10:49:23.412Z"``. We always emit the
    trailing ``Z`` (rather than ``+00:00``) because every downstream
    parser we care about (Loki, Elastic, jq) handles ``Z`` natively.
    """
    dt = datetime.datetime.fromtimestamp(epoch_seconds, tz=datetime.UTC)
    # Drop the microsecond field to millisecond precision; logs do not
    # benefit from sub-millisecond resolution and the shorter string is
    # easier to scan.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger for structured JSON output.

    Idempotent: any handlers already attached to the root logger are
    removed first. Subsequent calls therefore reflect the latest
    desired configuration rather than stacking handlers. Library code
    is expected to obtain a child logger via
    ``logging.getLogger("firm_bot.<module>")``; those loggers will
    inherit this handler and formatter automatically.
    """
    root = logging.getLogger()
    # ``logging.basicConfig`` is *additive*: re-running it stacks
    # handlers. We tear down explicitly so tests can flip the level
    # mid-run without duplicating output.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own handlers; replace them too so access
    # logs and our own log records share one JSON format.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(noisy)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        logger.propagate = True
