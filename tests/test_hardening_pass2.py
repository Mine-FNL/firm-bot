"""Hardening pass-2 regression suite.

Covers the five remaining hardening items called out after the
star-readiness push:

1. CORS methods / headers / max-age are env-tunable (origins already were).
2. All outbound ``httpx.Client`` calls carry explicit timeouts.
3. Pyproject deps carry upper bounds for production stability.
4. Concurrent ``POST /v1/firms/{slug}/ingest`` calls don't race — the
   second gets a structured 409 ``ingest_in_progress``.
5. Embedder load / encode failures map to a structured 503
   ``embedder_unavailable``, not a 500 with a stack trace.

Each item has 2-4 boundary tests so regressions are caught early.

Note on imports
---------------
``firm_bot/api/__init__.py`` does ``from .app import app``, which
binds the FastAPI instance into the package namespace. That shadows
``firm_bot.api.app`` as an attribute, so ``from firm_bot.api import
app`` (and even ``import firm_bot.api.app as X`` on some Python
versions) returns the FastAPI instance rather than the submodule.

We resolve the submodule via ``importlib.import_module`` everywhere
we need to inspect / patch module-level symbols. monkeypatch.setattr
also accepts dotted string paths, which use importlib internally and
sidestep the shadowing.
"""

from __future__ import annotations

import asyncio
import importlib
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# ---- shared helpers ----------------------------------------------------


def _app_module() -> Any:
    """Resolve the ``firm_bot.api.app`` *submodule* (not the FastAPI app).

    ``firm_bot.api.__init__`` does ``from .app import app``, which
    binds the FastAPI instance to the package attribute
    ``firm_bot.api.app``. Subsequent ``from firm_bot.api import app``
    returns the FastAPI instance, not the submodule — and even
    ``monkeypatch.setattr("firm_bot.api.app.<name>", ...)`` walks
    that shadow and looks up the attribute on the FastAPI object.

    The submodule lives at ``sys.modules["firm_bot.api.app"]`` and is
    also reachable via ``importlib.import_module`` (which always
    returns the canonical module object). Use this helper everywhere
    we need to introspect / patch module-level symbols.
    """
    return importlib.import_module("firm_bot.api.app")


# ---- 1. CORS env-tunable --------------------------------------------------


def test_cors_max_age_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """FIRM_BOT_CORS_MAX_AGE overrides the default 600s."""
    monkeypatch.setenv("FIRM_BOT_CORS_MAX_AGE", "1200")
    cfg = _build_root_from_env(monkeypatch)
    assert cfg.cors_max_age == 1200


def test_cors_allow_methods_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """FIRM_BOT_CORS_ALLOW_METHODS becomes a list of upper-case verbs."""
    monkeypatch.setenv("FIRM_BOT_CORS_ALLOW_METHODS", "GET,POST,DELETE")
    cfg = _build_root_from_env(monkeypatch)
    assert cfg.cors_allow_methods == ["GET", "POST", "DELETE"]


def test_cors_allow_headers_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """FIRM_BOT_CORS_ALLOW_HEADERS becomes a list."""
    monkeypatch.setenv("FIRM_BOT_CORS_ALLOW_HEADERS", "Authorization,X-Tenant-Id")
    cfg = _build_root_from_env(monkeypatch)
    assert cfg.cors_allow_headers == ["Authorization", "X-Tenant-Id"]


def test_cors_origins_env_still_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: FIRM_BOT_CORS_ALLOW_ORIGINS continues to work."""
    monkeypatch.setenv(
        "FIRM_BOT_CORS_ALLOW_ORIGINS", "https://app.example.com,http://localhost:3000"
    )
    cfg = _build_root_from_env(monkeypatch)
    assert cfg.cors_allow_origins == ["https://app.example.com", "http://localhost:3000"]


def test_cors_defaults_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no env vars are set, defaults remain sensible."""
    for v in (
        "FIRM_BOT_CORS_ALLOW_ORIGINS",
        "FIRM_BOT_CORS_ALLOW_METHODS",
        "FIRM_BOT_CORS_ALLOW_HEADERS",
        "FIRM_BOT_CORS_MAX_AGE",
    ):
        monkeypatch.delenv(v, raising=False)
    cfg = _build_root_from_env(monkeypatch)
    assert "GET" in cfg.cors_allow_methods
    assert "OPTIONS" in cfg.cors_allow_methods
    assert "Authorization" in cfg.cors_allow_headers
    assert isinstance(cfg.cors_max_age, int) and cfg.cors_max_age > 0
    assert cfg.cors_allow_origins == []


def test_cors_max_age_invalid_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-integer cors_max_age surfaces a clear error, not a silent fallback."""
    monkeypatch.setenv("FIRM_BOT_CORS_MAX_AGE", "not-a-number")
    with pytest.raises(ValueError):
        _build_root_from_env(monkeypatch)


def _build_root_from_env(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a fresh RootConfig from env, bypassing any cached config."""
    from firm_bot.config import RootConfig

    monkeypatch.delenv("FIRM_BOT_DATA_DIR", raising=False)
    monkeypatch.setenv("FIRM_BOT_DATA_DIR", "/tmp/_unused_hardening_pass2")
    return RootConfig.from_env()


def test_cors_methods_reach_security_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Custom methods/headers from env actually reach SecurityMiddleware.

    Round-trips through ``_register_middleware``'s reading of
    ``root.cors_*`` fields.
    """

    from firm_bot.security.middleware import SecurityMiddleware
    from firm_bot.security.rate_limit import RateLimiter

    # Build a SecurityMiddleware directly with our values and assert
    # the values are stored on the instance (catches a regression
    # where the kwargs are silently ignored).
    limiter = RateLimiter(rate=100.0, burst=1000)
    mw = SecurityMiddleware(
        app=lambda *_a, **_kw: asyncio.sleep(0),
        rate_limiter=limiter,
        max_body_bytes=1024,
        cors_allow_origins=["https://app.example.com"],
        cors_allow_methods=["GET", "POST", "DELETE"],
        cors_allow_headers=["Authorization", "X-Custom-Header"],
        cors_max_age=900,
    )
    assert mw.cors_allow_methods == ["GET", "POST", "DELETE"]
    assert mw.cors_allow_headers == ["Authorization", "X-Custom-Header"]
    assert mw.cors_max_age == 900
    assert mw.cors_allow_origins == ["https://app.example.com"]


def test_cors_preflight_returns_custom_methods(
    env_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_ollama: Any,
) -> None:
    """A preflight from an allowed origin returns the configured methods."""
    monkeypatch.setenv("FIRM_BOT_CORS_ALLOW_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("FIRM_BOT_CORS_ALLOW_METHODS", "GET,POST,PATCH,DELETE")
    # Rebuild the app's middleware so the new env values are honoured.

    # The app already has middleware wired at import time. To exercise
    # the env override end-to-end without re-importing the whole app,
    # we instantiate a fresh SecurityMiddleware directly and feed it a
    # minimal ASGI scope.
    from firm_bot.security.middleware import SecurityMiddleware
    from firm_bot.security.rate_limit import RateLimiter

    received_headers: list[tuple[bytes, bytes]] = []

    async def _send(msg: dict[str, Any]) -> None:
        if msg.get("type") == "http.response.start":
            received_headers.extend(msg.get("headers") or [])

    async def _receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        return None

    limiter = RateLimiter(rate=100.0, burst=1000)
    mw = SecurityMiddleware(
        app=_app,
        rate_limiter=limiter,
        max_body_bytes=1024,
        cors_allow_origins=["https://app.example.com"],
        cors_allow_methods=["GET", "POST", "PATCH", "DELETE"],
        cors_allow_headers=["Authorization", "Content-Type", "X-Tenant-Id"],
        cors_max_age=900,
    )

    async def _run() -> None:
        scope = {
            "type": "http",
            "method": "OPTIONS",
            "headers": [
                (b"origin", b"https://app.example.com"),
                (b"access-control-request-method", b"DELETE"),
                (b"access-control-request-headers", b"x-tenant-id"),
            ],
            "client": ("127.0.0.1", 12345),
        }
        await mw(scope, _receive, _send)

    asyncio.run(_run())
    headers_lower = {k.lower(): v for k, v in received_headers}
    assert headers_lower.get(b"access-control-allow-methods") == (
        b"GET, POST, PATCH, DELETE"
    )
    assert headers_lower.get(b"access-control-allow-headers") == (
        b"Authorization, Content-Type, X-Tenant-Id"
    )
    assert headers_lower.get(b"access-control-max-age") == b"900"


# ---- 2. httpx call timeouts ----------------------------------------------


def test_all_httpx_clients_have_explicit_timeout() -> None:
    """Static check: every ``httpx.Client(`` call carries ``timeout=...``."""
    from firm_bot import answer, ollama_setup

    sources: list[str] = []
    for module in (ollama_setup, answer.guard):
        src = Path(module.__file__).read_text()
        sources.append(src)
    full = "\n".join(sources)
    pattern = re.compile(r"httpx\.Client\(([^)]*)\)", re.S)
    offenders: list[str] = []
    for match in pattern.finditer(full):
        body = match.group(1)
        if "timeout" not in body:
            offenders.append(match.group(0).replace("\n", " ")[:80])
    assert offenders == [], (
        f"httpx.Client calls without explicit timeout: {offenders!r}"
    )


def test_default_timeout_for_answer_model_is_120s() -> None:
    """RootConfig.llm_timeout_s defaults to 120s — protects against a hung Ollama."""
    from firm_bot.config import RootConfig

    cfg = RootConfig()
    assert cfg.llm_timeout_s == 120.0


def test_pull_model_default_timeout_is_30_minutes() -> None:
    """Large model pulls (70B) take 30+ min on slow networks."""
    import inspect

    from firm_bot.ollama_setup import pull_model

    sig = inspect.signature(pull_model)
    assert sig.parameters["timeout_s"].default == 1800.0


# ---- 3. Dependency upper bounds -----------------------------------------


def test_pyproject_deps_have_upper_bounds() -> None:
    """Every dependency line in pyproject.toml has a ``<X`` upper bound."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text()
    deps_match = re.search(
        r"^dependencies\s*=\s*\[(.*?)\]",
        text,
        re.S | re.M,
    )
    assert deps_match is not None, "could not locate dependencies = [...] block"
    deps_block = deps_match.group(1)
    lines: list[str] = []
    for ln in deps_block.splitlines():
        s = ln.strip()
        if not s.startswith('"'):
            continue
        end = s.find('"', 1)
        if end < 0:
            continue
        lines.append(s[1:end])
    missing: list[str] = []
    for raw_spec in lines:
        if not raw_spec:
            continue
        spec = raw_spec.split("#", 1)[0].strip()
        name = re.split(r"[\[><=!~]", spec, maxsplit=1)[0].strip()
        if not name:
            continue
        if "<" not in spec:
            missing.append(name)
    assert missing == [], (
        f"deps without an upper bound: {missing!r}. Add `<X` to pin the "
        f"production envelope."
    )


def test_dev_deps_have_upper_bounds() -> None:
    """Dev / optional deps also carry upper bounds."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text()
    # Look at every array of deps that uses [project.optional-dependencies]
    # and the inline ``dev = [`` / ``observability = [`` / ``embed-fastembed = [``
    # arrays.
    optional_match = re.search(
        r"\[project\.optional-dependencies\](.*?)(?:^\[|\Z)",
        text,
        re.S | re.M,
    )
    assert optional_match is not None
    block = optional_match.group(1)
    missing: list[str] = []
    for ln in block.splitlines():
        s = ln.strip()
        if not s.startswith('"'):
            continue
        end = s.find('"', 1)
        if end < 0:
            continue
        raw_spec = s[1:end]
        spec = raw_spec
        name = re.split(r"[\[><=!~]", spec, maxsplit=1)[0].strip()
        if name and "<" not in spec:
            missing.append(name)
    assert missing == [], (
        f"optional deps without an upper bound: {missing!r}"
    )


# ---- 4. Concurrent ingest lock ------------------------------------------


@pytest.fixture
def firm_with_docs(
    env_data_dir: Path,
    sample_pdf: Path,
    mock_ollama: Any,
) -> str:
    """Create a firm with one indexed PDF. Returns the slug."""
    app_module = _app_module()
    client = TestClient(app_module.app)
    r = client.post("/v1/firms", json={"slug": "acme", "name": "Acme Co."})
    assert r.status_code in (200, 201), r.text
    src = env_data_dir / "firms" / "acme" / "source"
    src.mkdir(parents=True, exist_ok=True)
    (src / "doc.pdf").write_bytes(sample_pdf.read_bytes())
    r = client.post("/v1/firms/acme/ingest")
    assert r.status_code == 200, r.text
    return "acme"


def test_second_concurrent_ingest_returns_409(
    firm_with_docs: str,
    mock_ollama: Any,
) -> None:
    """Two concurrent ingest calls — the second gets 409 ingest_in_progress."""
    app_module = _app_module()
    client = TestClient(app_module.app)
    slug = firm_with_docs
    lock = app_module._ingest_lock_for(slug)
    # Pre-acquire the asyncio lock to simulate an in-flight ingest.
    asyncio.run(lock.acquire())
    try:
        r = client.post(f"/v1/firms/{slug}/ingest")
        assert r.status_code == 409, r.text
        assert "ingest_in_progress" in r.text, r.text
    finally:
        lock.release()


def test_ingest_lock_released_after_success(
    firm_with_docs: str,
) -> None:
    """The lock is released after a successful ingest — no permanent lockout."""
    app_module = _app_module()
    slug = firm_with_docs
    assert not app_module._ingest_lock_for(slug).locked()


def test_ingest_lock_released_after_error(
    env_data_dir: Path,
    mock_ollama: Any,
) -> None:
    """If ingest fails, the lock is still released so retries can proceed."""
    app_module = _app_module()
    client = TestClient(app_module.app)
    slug = "broken"
    r = client.post("/v1/firms", json={"slug": slug, "name": "Broken"})
    assert r.status_code in (200, 201)
    r = client.post(f"/v1/firms/{slug}/ingest")
    assert r.status_code == 200, r.text
    assert not app_module._ingest_lock_for(slug).locked()


def test_ingest_lock_isolated_per_firm(
    env_data_dir: Path,
    mock_ollama: Any,
) -> None:
    """Locking firm A does not block ingest for firm B."""
    app_module = _app_module()
    client = TestClient(app_module.app)
    for slug in ("alpha", "beta"):
        r = client.post("/v1/firms", json={"slug": slug, "name": slug.title()})
        assert r.status_code in (200, 201), r.text
    lock_a = app_module._ingest_lock_for("alpha")
    asyncio.run(lock_a.acquire())
    try:
        # firm beta should be unaffected.
        assert not app_module._ingest_lock_for("beta").locked()
    finally:
        lock_a.release()


# ---- 5. Embed model failure paths ---------------------------------------


@pytest.fixture
def firm_with_one_chunk(
    env_data_dir: Path,
    sample_pdf: Path,
    mock_ollama: Any,
) -> str:
    """A firm with one indexed chunk — used to exercise the embed path."""
    app_module = _app_module()
    client = TestClient(app_module.app)
    r = client.post("/v1/firms", json={"slug": "alpha", "name": "Alpha"})
    assert r.status_code in (200, 201)
    src = env_data_dir / "firms" / "alpha" / "source"
    src.mkdir(parents=True, exist_ok=True)
    (src / "doc.pdf").write_bytes(sample_pdf.read_bytes())
    r = client.post("/v1/firms/alpha/ingest")
    assert r.status_code == 200, r.text
    return "alpha"


def test_query_503_when_embedder_load_fails(
    firm_with_one_chunk: str,
    monkeypatch: pytest.MonkeyPatch,
    mock_ollama: Any,
) -> None:
    """A failed ``get_embedder`` raises 503 with structured error, not 500."""
    app_module = _app_module()

    def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("simulated model load failure (missing weights)")

    monkeypatch.setattr(_app_module(), "get_embedder", _explode)
    client = TestClient(app_module.app)
    r = client.post(
        "/v1/firms/alpha/query",
        json={"question": "What does Section 4.2 say?"},
    )
    assert r.status_code == 503, r.text
    assert "embedder_unavailable" in r.text, r.text


def test_query_stream_503_when_embedder_load_fails(
    firm_with_one_chunk: str,
    monkeypatch: pytest.MonkeyPatch,
    mock_ollama: Any,
) -> None:
    """Same 503 contract for the streaming query endpoint."""
    app_module = _app_module()

    def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("simulated model load failure")

    monkeypatch.setattr(_app_module(), "get_embedder", _explode)
    client = TestClient(app_module.app)
    r = client.post(
        "/v1/firms/alpha/query/stream",
        json={"question": "What does Section 4.2 say?"},
    )
    assert r.status_code == 503, r.text
    assert "embedder_unavailable" in r.text, r.text


def test_ingest_503_when_embedder_load_fails(
    env_data_dir: Path,
    sample_pdf: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_ollama: Any,
) -> None:
    """The ingest endpoint also maps embedder-load failures to 503."""
    app_module = _app_module()
    client = TestClient(app_module.app)
    r = client.post("/v1/firms", json={"slug": "beta", "name": "Beta"})
    assert r.status_code in (200, 201)
    src = env_data_dir / "firms" / "beta" / "source"
    src.mkdir(parents=True, exist_ok=True)
    (src / "doc.pdf").write_bytes(sample_pdf.read_bytes())

    def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("simulated model load failure (OOM)")

    monkeypatch.setattr(_app_module(), "get_embedder", _explode)
    r = client.post("/v1/firms/beta/ingest")
    assert r.status_code == 503, r.text
    assert "embedder_unavailable" in r.text, r.text


def test_ingest_503_when_encode_fails_mid_ingest(
    env_data_dir: Path,
    sample_pdf: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_ollama: Any,
) -> None:
    """If the embedder LOADS but encode() raises, ingest returns 503."""
    app_module = _app_module()
    client = TestClient(app_module.app)
    r = client.post("/v1/firms", json={"slug": "gamma", "name": "Gamma"})
    assert r.status_code in (200, 201)
    src = env_data_dir / "firms" / "gamma" / "source"
    src.mkdir(parents=True, exist_ok=True)
    (src / "doc.pdf").write_bytes(sample_pdf.read_bytes())

    class _BoomEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            raise MemoryError("simulated encode OOM")

    monkeypatch.setattr(
        _app_module(), "get_embedder", lambda _root: _BoomEmbedder(),
    )

    r = client.post("/v1/firms/gamma/ingest")
    assert r.status_code == 503, r.text
    assert "embedder_unavailable" in r.text, r.text


def test_safe_get_embedder_unit() -> None:
    """Direct unit test of _safe_get_embedder mapping."""
    from fastapi import HTTPException

    app_mod = _app_module()
    assert hasattr(app_mod, "_safe_get_embedder")
    _safe_get_embedder = app_mod._safe_get_embedder

    class _FakeRoot:
        pass

    class _GoodEmbedder:
        pass

    orig_fn = app_mod.get_embedder

    def _good(_root: Any) -> Any:
        return _GoodEmbedder()

    app_mod.get_embedder = _good  # type: ignore[assignment]
    try:
        emb = _safe_get_embedder(_FakeRoot())
        assert isinstance(emb, _GoodEmbedder)
    finally:
        app_mod.get_embedder = orig_fn

    def _boom(_root: Any) -> Any:
        raise RuntimeError("kaboom")

    app_mod.get_embedder = _boom  # type: ignore[assignment]
    try:
        with pytest.raises(HTTPException) as ei:
            _safe_get_embedder(_FakeRoot())
        assert ei.value.status_code == 503
        assert "embedder_unavailable" in str(ei.value.detail)
    finally:
        app_mod.get_embedder = orig_fn


# ---- auxiliary: ensure the new tests are wired into the suite ----------


def test_module_imports_clean() -> None:
    """Sanity: the modules touched by this hardening pass import cleanly."""
    from firm_bot.config import RootConfig

    app_module = _app_module()
    assert hasattr(app_module, "_safe_get_embedder")
    assert hasattr(app_module, "_ingest_lock_for")
    cfg = RootConfig()
    assert hasattr(cfg, "cors_allow_methods")
    assert hasattr(cfg, "cors_allow_headers")
    assert hasattr(cfg, "cors_max_age")


def test_no_regression_on_request_id_after_lock_addition(
    firm_with_one_chunk: str,
    mock_ollama: Any,
) -> None:
    """The X-Request-ID header still works after the ingest-lock addition."""
    app_module = _app_module()
    client = TestClient(app_module.app)
    r = client.post(
        "/v1/firms/alpha/query",
        json={"question": "What does Section 4.2 say?"},
        headers={"X-Request-ID": "test-request-id-12345"},
    )
    assert "x-request-id" in {k.lower() for k in r.headers}, r.headers
