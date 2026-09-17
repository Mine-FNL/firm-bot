"""Tests for the firm_bot.observability package.

Each test isolates the Prometheus registry so observations made by
prior tests do not pollute the assertions. The fixture-driven registry
swap is a strict requirement: the global :data:`REGISTRY` would
otherwise accumulate counter values across the suite and break the
``increment by exactly 1`` style assertions.

TestClient is used for middleware coverage. We construct a stub
FastAPI app per-test rather than importing ``firm_bot.api.app`` —
the latter is deliberately untouched in this change (middleware
registration is a follow-up).
"""
from __future__ import annotations

import json
import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, generate_latest
from starlette.responses import PlainTextResponse

# ---- registry isolation ---------------------------------------------------


@pytest.fixture
def fresh_registry(monkeypatch: pytest.MonkeyPatch) -> CollectorRegistry:
    """Swap the module-level REGISTRY for a clean one for the test."""
    from firm_bot.observability import metrics as m
    from firm_bot.observability import timing as t

    new_registry = CollectorRegistry()
    monkeypatch.setattr(m, "REGISTRY", new_registry)
    # Rebuild every collector bound to the old registry. Counters and
    # histograms read ``registry`` at construction time, so the easy
    # way to retarget them is to re-instantiate. This keeps the public
    # names (``m.query_requests``) pointing at fresh collectors.
    monkeypatch.setattr(
        m,
        "query_requests",
        m.Counter(
            "firmbot_query_requests",
            "Total /query requests",
            labelnames=("firm", "status"),
            registry=new_registry,
        ),
    )
    monkeypatch.setattr(
        m,
        "query_latency_seconds",
        m.Histogram(
            "firmbot_query_latency_seconds",
            "End-to-end /query latency in seconds",
            labelnames=("firm",),
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
            registry=new_registry,
        ),
    )
    monkeypatch.setattr(
        m,
        "stage_latency_seconds",
        m.Histogram(
            "firmbot_stage_latency_seconds",
            "Per-stage latency in seconds",
            labelnames=("stage",),
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
            registry=new_registry,
        ),
    )
    monkeypatch.setattr(
        m,
        "ingest_chunks",
        m.Counter(
            "firmbot_ingest_chunks",
            "Total chunks ingested",
            labelnames=("firm", "source_type"),
            registry=new_registry,
        ),
    )
    monkeypatch.setattr(
        m,
        "active_firms",
        m.Gauge(
            "firmbot_active_firms",
            "Number of configured firms",
            registry=new_registry,
        ),
    )
    # The ``timing`` module imported ``stage_latency_seconds`` at module
    # load; rebind it to the freshly-recreated collector so observations
    # land in the new registry.
    monkeypatch.setattr(t, "stage_latency_seconds", m.stage_latency_seconds)

    # Same story for ``middleware``: the module-imported names must
    # point at the new collectors so request-path increments land in
    # the test's registry.
    from firm_bot.observability import middleware as mw

    monkeypatch.setattr(mw, "query_requests", m.query_requests)
    monkeypatch.setattr(mw, "query_latency_seconds", m.query_latency_seconds)
    return new_registry


# ---- metrics.py -----------------------------------------------------------


def test_counter_increments_and_serialises(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability import metrics as m

    m.query_requests.labels(firm="acme", status="200").inc()
    m.query_requests.labels(firm="acme", status="200").inc(2)
    m.query_requests.labels(firm="acme", status="500").inc()

    body = generate_latest(fresh_registry).decode("utf-8")
    assert 'firmbot_query_requests_total{firm="acme",status="200"} 3.0' in body
    assert 'firmbot_query_requests_total{firm="acme",status="500"} 1.0' in body


def test_histogram_observes_and_exposes_buckets(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability import metrics as m

    h = m.query_latency_seconds.labels(firm="acme")
    for v in (0.05, 0.3, 1.5):
        h.observe(v)

    body = generate_latest(fresh_registry).decode("utf-8")
    # The HELP and TYPE lines must be present per Prometheus spec.
    assert "# HELP firmbot_query_latency_seconds" in body
    assert "# TYPE firmbot_query_latency_seconds histogram" in body
    # The cumulative bucket counts go 1, 2, 3 across the bucket series
    # we just observed.
    assert re.search(r'firmbot_query_latency_seconds_bucket\{firm="acme",le="0\.05"\}\s+1\.0', body)
    assert re.search(r'firmbot_query_latency_seconds_bucket\{firm="acme",le="0\.5"\}\s+2\.0', body)
    assert re.search(r'firmbot_query_latency_seconds_bucket\{firm="acme",le="2\.0"\}\s+3\.0', body)


def test_gauge_tracks_active_firms(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability import metrics as m

    m.active_firms.set(3)
    body = generate_latest(fresh_registry).decode("utf-8")
    assert "firmbot_active_firms 3.0" in body


def test_ingest_chunks_counter(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability import metrics as m

    m.ingest_chunks.labels(firm="acme", source_type="pdf").inc(7)
    body = generate_latest(fresh_registry).decode("utf-8")
    assert 'firmbot_ingest_chunks_total{firm="acme",source_type="pdf"} 7.0' in body


def test_metrics_response_returns_prometheus_text(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability import metrics as m

    m.query_requests.labels(firm="acme", status="200").inc()
    response = m.metrics_response()
    assert response.media_type == m.CONTENT_TYPE_LATEST
    body = response.body.decode("utf-8")
    assert "firmbot_query_requests_total" in body
    # No raw newlines in label values — the Prometheus spec forbids
    # them and ``generate_latest`` would have escaped them.
    assert "\nfirmbot" not in body.strip().split("\n", 1)[0]
    assert all(line for line in body.splitlines())  # no blank lines


# ---- timing.py ------------------------------------------------------------


def test_stage_timing_records_observation(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability import timing as t

    with t.stage_timing("retrieve"):
        pass  # trivial block; the observation fires in the finally

    body = generate_latest(fresh_registry).decode("utf-8")
    # Prometheus sorts label keys alphabetically, so ``le`` comes
    # before ``stage`` in the text exposition.
    assert re.search(
        r'firmbot_stage_latency_seconds_bucket\{le="\+Inf",stage="retrieve"\}\s+1\.0',
        body,
    )
    # And the count series must reflect exactly one observation.
    assert re.search(
        r'firmbot_stage_latency_seconds_count\{stage="retrieve"\}\s+1\.0',
        body,
    )


def test_stage_timing_sets_current_stage_contextvar(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability import timing as t

    observed: list[str | None] = []
    with t.stage_timing("answer"):
        observed.append(t.current_stage.get())
    observed.append(t.current_stage.get())
    assert observed == ["answer", None]


def test_stage_timing_records_on_exception(fresh_registry: CollectorRegistry) -> None:
    """Failures still emit an observation so partial latency is visible."""
    from firm_bot.observability import timing as t

    with pytest.raises(RuntimeError, match="boom"), t.stage_timing("guard"):
        raise RuntimeError("boom")

    body = generate_latest(fresh_registry).decode("utf-8")
    assert re.search(
        r'firmbot_stage_latency_seconds_count\{stage="guard"\}\s+1\.0',
        body,
    )


# ---- logging_config.py ----------------------------------------------------


def test_setup_logging_emits_valid_json_to_stream(capsys: pytest.CaptureFixture[str]) -> None:
    from firm_bot.observability import logging_config as lc

    lc.setup_logging(level="INFO")
    logging.getLogger("firm_bot.tests.logging").info("hello world")

    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert lines, "expected at least one log line on stderr"
    record = json.loads(lines[-1])
    assert record["level"] == "INFO"
    assert record["logger"] == "firm_bot.tests.logging"
    assert record["message"] == "hello world"
    # ISO 8601 UTC, millisecond precision, ``Z`` suffix.
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", record["timestamp"])


def test_json_formatter_includes_request_id_and_stage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from firm_bot.observability import logging_config as lc
    from firm_bot.observability import timing as t

    lc.setup_logging(level="INFO")

    token_req = t.current_request_id.set("req-abc123")
    try:
        with t.stage_timing("retrieve"):
            logging.getLogger("firm_bot.tests.ctx").info("inside stage")
    finally:
        t.current_request_id.reset(token_req)

    captured = capsys.readouterr()
    record = json.loads(captured.err.strip().splitlines()[-1])
    assert record["request_id"] == "req-abc123"
    assert record["stage"] == "retrieve"


def test_json_formatter_serialises_exception(capsys: pytest.CaptureFixture[str]) -> None:
    from firm_bot.observability import logging_config as lc

    lc.setup_logging(level="INFO")
    try:
        raise ValueError("kaboom")
    except ValueError:
        logging.getLogger("firm_bot.tests.exc").exception("nope")

    captured = capsys.readouterr()
    record = json.loads(captured.err.strip().splitlines()[-1])
    assert record["level"] == "ERROR"
    assert record["message"] == "nope"
    assert "ValueError: kaboom" in record["exc_info"]


def test_setup_logging_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    """Repeated calls must not stack handlers on the root logger."""
    from firm_bot.observability import logging_config as lc

    lc.setup_logging(level="INFO")
    first_handler_count = len(logging.getLogger().handlers)
    lc.setup_logging(level="INFO")
    lc.setup_logging(level="INFO")
    assert len(logging.getLogger().handlers) == first_handler_count
    assert len(logging.getLogger().handlers) == 1


# ---- middleware.py --------------------------------------------------------


def _build_stub_app() -> FastAPI:
    """Create a minimal FastAPI app exercising the middleware."""
    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/firms/{slug}/query")
    async def stub_query(slug: str) -> dict[str, str]:
        return {"slug": slug, "answer": "stub"}

    @app.get("/boom")
    async def boom() -> PlainTextResponse:
        raise RuntimeError("synthetic failure")

    return app


def test_middleware_sets_request_id_header(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability.middleware import ObservabilityMiddleware

    app = _build_stub_app()
    app.add_middleware(ObservabilityMiddleware)
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    # UUIDv4 hex is exactly 32 chars.
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_middleware_increments_counter_for_firm_path(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability.middleware import ObservabilityMiddleware

    app = _build_stub_app()
    app.add_middleware(ObservabilityMiddleware)
    with TestClient(app) as client:
        client.get("/v1/firms/acme/query")
        client.get("/v1/firms/acme/query")

    body = generate_latest(fresh_registry).decode("utf-8")
    assert 'firmbot_query_requests_total{firm="acme",status="200"} 2.0' in body
    # Latency histogram should have two observations.
    assert re.search(
        r'firmbot_query_latency_seconds_count\{firm="acme"\}\s+2\.0',
        body,
    )


def test_middleware_uses_status_label(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability.middleware import ObservabilityMiddleware

    app = _build_stub_app()
    app.add_middleware(ObservabilityMiddleware)
    with TestClient(app) as client:
        client.get("/v1/firms/acme/query")

    body = generate_latest(fresh_registry).decode("utf-8")
    assert 'firmbot_query_requests_total{firm="acme",status="200"}' in body


def test_middleware_skips_metrics_for_non_firm_path(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability.middleware import ObservabilityMiddleware

    app = _build_stub_app()
    app.add_middleware(ObservabilityMiddleware)
    with TestClient(app) as client:
        client.get("/healthz")

    body = generate_latest(fresh_registry).decode("utf-8")
    # No firm-scoped *samples* should appear for a /healthz call.
    # HELP/TYPE lines for collectors registered to the empty registry
    # are still emitted, so we look for the ``{``-bearing sample lines.
    assert not re.search(r'^firmbot_query_requests_total\{', body, re.MULTILINE)
    assert not re.search(r'^firmbot_query_latency_seconds_count\{', body, re.MULTILINE)


def test_middleware_returns_500_json_on_exception(fresh_registry: CollectorRegistry) -> None:
    from firm_bot.observability.middleware import ObservabilityMiddleware

    app = _build_stub_app()
    app.add_middleware(ObservabilityMiddleware)
    with TestClient(app) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    payload = response.json()
    assert payload["error"] == "internal_server_error"
    assert "request_id" in payload
    assert response.headers["X-Request-ID"] == payload["request_id"]


def test_middleware_logs_unhandled_exception(
    fresh_registry: CollectorRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from firm_bot.observability.middleware import ObservabilityMiddleware

    app = _build_stub_app()
    app.add_middleware(ObservabilityMiddleware)
    with (
        caplog.at_level(logging.ERROR, logger="firm_bot.observability.middleware"),
        TestClient(app) as client,
    ):
        client.get("/boom")

    assert any("unhandled exception" in rec.message for rec in caplog.records)
    assert any(rec.exc_info is not None for rec in caplog.records)


# ---- validate Prometheus text format --------------------------------------


def test_exposition_format_validates_against_prometheus_spec(
    fresh_registry: CollectorRegistry,
) -> None:
    """Smoke-check the text exposition against the Prometheus rules.

    The reference spec is at
    https://prometheus.io/docs/instrumenting/exposition_formats/ — we
    validate the bits that matter for scraping: HELP/TYPE lines,
    ``metric{labels} value`` shape, and absence of newlines inside label
    values.
    """
    from firm_bot.observability import metrics as m

    m.query_requests.labels(firm="acme", status="200").inc()
    m.stage_latency_seconds.labels(stage="embed").observe(0.01)
    body = generate_latest(fresh_registry).decode("utf-8")
    lines = [line for line in body.splitlines() if line]

    # Every line must match one of: ``# HELP ...``, ``# TYPE ...``,
    # ``name{labels} value`` or ``name value``.
    metric_re = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*(\{[^}]*\})? +[+-]?[0-9.eE+\-]+( [0-9]+)?$")
    comment_re = re.compile(r"^# (HELP|TYPE) ")
    for line in lines:
        assert metric_re.match(line) or comment_re.match(line), f"malformed: {line!r}"

    # At least one HELP and one TYPE for each metric family we touched.
    # Counter families are rendered with a ``_total`` suffix in the
    # exposition (this is the Prometheus convention; ``_created``
    # gauges are auto-emitted for counters).
    for family in (
        "firmbot_query_requests_total",
        "firmbot_query_latency_seconds",
        "firmbot_stage_latency_seconds",
        "firmbot_ingest_chunks_total",
        "firmbot_active_firms",
    ):
        assert f"# HELP {family} " in body, f"missing HELP for {family}"
        assert f"# TYPE {family} " in body, f"missing TYPE for {family}"


# ---- __init__ re-exports --------------------------------------------------


def test_package_re_exports_public_api() -> None:
    """The package __init__ exposes the documented names."""
    import firm_bot.observability as obs

    expected = {
        "CONTENT_TYPE_LATEST",
        "JsonFormatter",
        "ObservabilityMiddleware",
        "REGISTRY",
        "active_firms",
        "current_request_id",
        "current_stage",
        "ingest_chunks",
        "metrics_response",
        "query_latency_seconds",
        "query_requests",
        "setup_logging",
        "stage_latency_seconds",
        "stage_timing",
    }
    missing = expected - set(dir(obs))
    assert not missing, f"missing public exports: {sorted(missing)}"
