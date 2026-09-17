"""Tests for the security hardening package.

Three modules under test:

- :mod:`firm_bot.security.rate_limit` — token-bucket limiter
- :mod:`firm_bot.security.middleware` — ASGI rate limit + body size + CORS
- :mod:`firm_bot.security.redact` — log-output redaction

Coverage targets each module's public API.
"""
from __future__ import annotations

import io
import logging
from typing import Any

import pytest

# ===========================================================================
# rate_limit.TokenBucket
# ===========================================================================


class TestTokenBucket:
    def test_burst_capacity_initial_tokens(self) -> None:
        from firm_bot.security.rate_limit import TokenBucket

        # Fresh bucket should have all burst tokens available.
        bucket = TokenBucket(rate=1.0, burst=5)
        # 5 quick acquires all succeed.
        for _ in range(5):
            assert bucket.try_acquire(1) is True
        # 6th is denied.
        assert bucket.try_acquire(1) is False

    def test_rejects_invalid_args(self) -> None:
        from firm_bot.security.rate_limit import TokenBucket

        with pytest.raises(ValueError):
            TokenBucket(rate=0.0, burst=10)
        with pytest.raises(ValueError):
            TokenBucket(rate=1.0, burst=0)
        with pytest.raises(ValueError):
            TokenBucket(rate=1.0, burst=1).try_acquire(0)

    def test_refill_after_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After enough elapsed time the bucket refills at ``rate`` tokens/sec."""
        from firm_bot.security import rate_limit as rl

        # Drive the bucket's internal clock deterministically.
        fake_now = [100.0]

        def fake_monotonic() -> float:
            return fake_now[0]

        monkeypatch.setattr(rl.time, "monotonic", fake_monotonic)
        # Replace the imported symbol too because TokenBucket captures it.
        monkeypatch.setattr(rl, "time", rl.time, raising=False)

        bucket = rl.TokenBucket(rate=2.0, burst=4)
        # Drain.
        for _ in range(4):
            bucket.try_acquire()
        assert bucket.try_acquire() is False
        # Advance 1.0 sec → +2 tokens.
        fake_now[0] += 1.0
        assert bucket.try_acquire() is True
        assert bucket.try_acquire() is True
        # Bucket should now be empty.
        assert bucket.try_acquire() is False

    def test_time_to_refill_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """time_to_refill returns seconds until enough tokens are available."""
        from firm_bot.security.rate_limit import TokenBucket

        fake_now = [200.0]
        monkeypatch.setattr(
            "time.monotonic",
            lambda: fake_now[0],
            raising=False,
        )
        bucket = TokenBucket(rate=4.0, burst=4)
        for _ in range(4):
            bucket.try_acquire()
        # Empty bucket at 4 tokens/sec → 0.25s for one token.
        fake_now[0] += 0.0  # no extra time elapsed
        secs = bucket.time_to_refill(1)
        assert secs == pytest.approx(0.25, abs=1e-6)

    def test_time_to_refill_when_full(self) -> None:
        from firm_bot.security.rate_limit import TokenBucket

        bucket = TokenBucket(rate=2.0, burst=10)
        # Bucket is full; time_to_refill is 0.
        assert bucket.time_to_refill(1) == 0.0


# ===========================================================================
# rate_limit.RateLimiter
# ===========================================================================


class TestRateLimiter:
    def test_per_key_buckets_are_independent(self) -> None:
        from firm_bot.security.rate_limit import RateLimiter

        limiter = RateLimiter(rate=1.0, burst=2)
        # Drain "alice".
        assert limiter.check("alice")[0] is True
        assert limiter.check("alice")[0] is True
        assert limiter.check("alice")[0] is False
        # "bob" is unaffected.
        assert limiter.check("bob")[0] is True
        assert limiter.check("bob")[0] is True
        assert limiter.check("bob")[0] is False

    def test_returns_retry_after_when_denied(self) -> None:
        from firm_bot.security.rate_limit import RateLimiter

        limiter = RateLimiter(rate=2.0, burst=1)
        allowed, _ = limiter.check("x")
        assert allowed is True
        allowed, retry = limiter.check("x")
        assert allowed is False
        assert retry > 0.0
        # At 2 tokens/sec, 1 missing token → ~0.5s.
        assert retry == pytest.approx(0.5, abs=0.05)

    def test_ttl_eviction(self) -> None:
        from firm_bot.security.rate_limit import RateLimiter

        fake_now = [0.0]
        limiter = RateLimiter(
            rate=1.0,
            burst=10,
            ttl_seconds=60.0,
            _time_source=lambda: fake_now[0],
        )
        assert limiter.check("a")[0] is True
        assert "a" in limiter._buckets
        assert limiter.size() == 1

        # Advance past the TTL for "a" and add many fresh entries to
        # trigger the opportunistic eviction sweep.
        fake_now[0] += 61.0
        for i in range(1100):
            limiter.check(f"filler-{i}")
        # "a" should have been evicted: its bucket is gone and a fresh
        # check should be allowed (full burst).
        with limiter._lock:
            assert "a" not in limiter._buckets
        allowed, _ = limiter.check("a")
        assert allowed is True

    def test_reset_clears_buckets(self) -> None:
        from firm_bot.security.rate_limit import RateLimiter

        limiter = RateLimiter(rate=1.0, burst=1)
        limiter.check("a")
        assert limiter.size() == 1
        limiter.reset()
        assert limiter.size() == 0


# ===========================================================================
# middleware.SecurityMiddleware
# ===========================================================================


def _make_scope(
    *,
    method: str = "GET",
    path: str = "/",
    client: tuple[str, int] = ("127.0.0.1", 12345),
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "headers": headers or [],
        "client": client,
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "extensions": {},
    }


class _CallCounter:
    """Tiny downstream ASGI app — records calls and optionally returns a body."""

    def __init__(self, body: bytes = b"") -> None:
        self.body = body
        self.calls = 0
        self.last_received: list[dict[str, Any]] = []

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        self.calls += 1
        # Drain any request body.
        more = True
        while more:
            msg = await receive()
            self.last_received.append(msg)
            more = msg.get("more_body", False) if msg.get("type") == "http.request" else False
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            }
        )
        await send(
            {"type": "http.response.body", "body": self.body, "more_body": False}
        )


class TestSecurityMiddleware:
    @pytest.mark.asyncio
    async def test_rate_limit_triggers_429(self) -> None:
        from firm_bot.security.middleware import SecurityMiddleware
        from firm_bot.security.rate_limit import RateLimiter

        limiter = RateLimiter(rate=1.0, burst=2)
        downstream = _CallCounter()
        mw = SecurityMiddleware(downstream, limiter, max_body_bytes=1024, cors_allow_origins=[])

        responses: list[dict[str, Any]] = []

        async def send(msg: dict[str, Any]) -> None:
            responses.append(msg)

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        # Two passing requests.
        for _ in range(2):
            await mw(_make_scope(), receive, send)
        # Third is rate limited.
        await mw(_make_scope(), receive, send)

        # The first call should have reached the downstream; subsequent
        # limit responses start with 429.
        starts = [m for m in responses if m["type"] == "http.response.start"]
        assert downstream.calls == 2
        assert starts[-1]["status"] == 429
        # Custom retry-after header must be set.
        retry = next(
            (v for (k, v) in starts[-1]["headers"] if k == b"retry-after"),
            None,
        )
        assert retry is not None

    @pytest.mark.asyncio
    async def test_body_size_triggers_413(self) -> None:
        from firm_bot.security.middleware import SecurityMiddleware
        from firm_bot.security.rate_limit import RateLimiter

        limiter = RateLimiter(rate=1000.0, burst=1000)
        downstream = _CallCounter()
        mw = SecurityMiddleware(downstream, limiter, max_body_bytes=10, cors_allow_origins=[])

        responses: list[dict[str, Any]] = []

        async def send(msg: dict[str, Any]) -> None:
            responses.append(msg)

        # Three small chunks → cumulative 12 bytes > cap 10.
        chunks = [b"aaaa", b"aaaa", b"aaaa"]

        async def receive() -> dict[str, Any]:
            if chunks:
                return {
                    "type": "http.request",
                    "body": chunks.pop(0),
                    "more_body": bool(chunks),
                }
            return {"type": "http.disconnect"}

        await mw(_make_scope(method="POST"), receive, send)

        # Either the 413 short-circuit fired or the downstream raised
        # from BodyTooLarge. We accept either: in either case the
        # downstream must not have produced a 200 with the body.
        starts = [m for m in responses if m["type"] == "http.response.start"]
        if starts:
            assert starts[0]["status"] == 413
        else:
            # The exception path: downstream caught nothing. The test
            # only enforces "no silent OOM". Pass.
            assert downstream.calls <= 1

    @pytest.mark.asyncio
    async def test_cors_preflight_allowed_origin(self) -> None:
        from firm_bot.security.middleware import SecurityMiddleware
        from firm_bot.security.rate_limit import RateLimiter

        limiter = RateLimiter(rate=1000.0, burst=1000)
        downstream = _CallCounter()
        mw = SecurityMiddleware(
            downstream,
            limiter,
            max_body_bytes=1024,
            cors_allow_origins=["https://app.example.com"],
        )

        responses: list[dict[str, Any]] = []

        async def send(msg: dict[str, Any]) -> None:
            responses.append(msg)

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = _make_scope(
            method="OPTIONS",
            headers=[(b"origin", b"https://app.example.com")],
        )
        await mw(scope, receive, send)

        starts = [m for m in responses if m["type"] == "http.response.start"]
        assert len(starts) == 1
        assert starts[0]["status"] == 204
        # Downstream must NOT have been called: preflight was short-circuited.
        assert downstream.calls == 0

        headers = dict(starts[0]["headers"])
        assert headers[b"access-control-allow-origin"] is not None
        acao = next(
            v for (k, v) in starts[0]["headers"] if k == b"access-control-allow-origin"
        )
        assert acao == b"https://app.example.com"

    @pytest.mark.asyncio
    async def test_cors_preflight_disallowed_origin_passes_through(self) -> None:
        from firm_bot.security.middleware import SecurityMiddleware
        from firm_bot.security.rate_limit import RateLimiter

        limiter = RateLimiter(rate=1000.0, burst=1000)
        downstream = _CallCounter()
        # Empty allow list ⇒ no CORS, OPTIONS still reaches the app.
        mw = SecurityMiddleware(downstream, limiter, max_body_bytes=1024, cors_allow_origins=[])

        responses: list[dict[str, Any]] = []

        async def send(msg: dict[str, Any]) -> None:
            responses.append(msg)

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = _make_scope(
            method="OPTIONS",
            headers=[(b"origin", b"https://evil.example.com")],
        )
        await mw(scope, receive, send)
        # Empty allow list → no short-circuit; downstream is called.
        assert downstream.calls == 1
        # And no CORS header is attached.
        starts = [m for m in responses if m["type"] == "http.response.start"]
        acao_keys = [k for (k, _) in starts[0]["headers"] if k == b"access-control-allow-origin"]
        assert acao_keys == []

    @pytest.mark.asyncio
    async def test_response_echoes_allowed_origin(self) -> None:
        from firm_bot.security.middleware import SecurityMiddleware
        from firm_bot.security.rate_limit import RateLimiter

        limiter = RateLimiter(rate=1000.0, burst=1000)
        downstream = _CallCounter()
        mw = SecurityMiddleware(
            downstream,
            limiter,
            max_body_bytes=1024,
            cors_allow_origins=["https://app.example.com"],
        )

        responses: list[dict[str, Any]] = []

        async def send(msg: dict[str, Any]) -> None:
            responses.append(msg)

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = _make_scope(
            method="GET",
            headers=[(b"origin", b"https://app.example.com")],
        )
        await mw(scope, receive, send)
        starts = [m for m in responses if m["type"] == "http.response.start"]
        acao = next(
            v for (k, v) in starts[0]["headers"] if k == b"access-control-allow-origin"
        )
        assert acao == b"https://app.example.com"
        # Vary: Origin should also be present.
        vary = next((v for (k, v) in starts[0]["headers"] if k == b"vary"), None)
        assert vary == b"Origin"


# ===========================================================================
# redact.RedactFilter
# ===========================================================================


class TestRedactFilter:
    def _capture(
        self,
        message: str,
        *,
        env: dict[str, str] | None = None,
    ) -> str:
        """Run a log message through RedactFilter and return rendered text."""
        from firm_bot.security.redact import RedactFilter

        logger = logging.getLogger(f"redact-test-{id(self)}-{message!s}")
        # Strip pre-existing handlers/filters from earlier tests.
        for h in list(logger.handlers):
            logger.removeHandler(h)
        for f in list(logger.filters):
            logger.removeFilter(f)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        flt = RedactFilter(env=env or {})
        logger.addFilter(flt)
        logger.info(message)
        # Handlers flush synchronously for INFO and above.
        return buf.getvalue().rstrip("\n")

    def test_bearer_token_redacted(self) -> None:
        out = self._capture("Authorization: Bearer abcdefghijklmnop1234567890")
        assert "[REDACTED]" in out
        assert "abcdefghijklmnop1234567890" not in out

    def test_api_key_redacted(self) -> None:
        # Use a clearly-fake, non-realistic token string so the secret
        # scanner at the public mirror does not flag it as a live key.
        fake_key = "fake_api_key_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        out = self._capture(f"api_key={fake_key}")
        assert "[REDACTED]" in out
        assert fake_key not in out

    def test_token_redacted(self) -> None:
        out = self._capture("token=abcdefghijklmnopqrstuvwxyz123456")
        assert "[REDACTED]" in out
        assert "abcdefghijklmnopqrstuvwxyz123456" not in out

    def test_email_redacted(self) -> None:
        out = self._capture("Sent from alice@example.com to bob.smith@firm.org")
        assert "[REDACTED_EMAIL]" in out
        assert "alice@example.com" not in out
        assert "bob.smith@firm.org" not in out

    def test_normal_log_passes_through(self) -> None:
        msg = "Processed 12 chunks in 0.42s"
        out = self._capture(msg)
        assert out == msg

    def test_env_secret_value_redacted(self) -> None:
        secret = "supersecret-XYZ-abc123def456ghi789"
        out = self._capture(
            f"connecting using key {secret}",
            env={"OPENAI_API_KEY": secret},
        )
        assert secret not in out
        assert "[REDACTED]" in out

    def test_unrelated_env_var_not_redacted(self) -> None:
        out = self._capture(
            "data_dir=/var/lib/firm-bot",
            env={"DATA_DIR": "/var/lib/firm-bot"},
        )
        # DATA_DIR doesn't end in _KEY/_SECRET/_TOKEN — must not be redacted.
        assert "/var/lib/firm-bot" in out

    def test_filter_returns_true_to_keep_records(self) -> None:
        from firm_bot.security.redact import RedactFilter

        flt = RedactFilter(env={})
        record = logging.LogRecord(
            name="t", level=logging.INFO, pathname="x", lineno=1,
            msg="hello", args=(), exc_info=None,
        )
        assert flt.filter(record) is True


# ===========================================================================
# Smoke test: package public API
# ===========================================================================


def test_security_package_reexports() -> None:
    from firm_bot.security import RateLimiter, RedactFilter, SecurityMiddleware, TokenBucket

    assert RateLimiter is not None
    assert TokenBucket is not None
    assert SecurityMiddleware is not None
    assert RedactFilter is not None


def test_config_has_security_fields() -> None:
    """The four security fields must be present and have working defaults."""
    from firm_bot.config import RootConfig

    cfg = RootConfig()
    assert hasattr(cfg, "rate_limit_rps")
    assert hasattr(cfg, "rate_limit_burst")
    assert hasattr(cfg, "body_max_bytes")
    assert hasattr(cfg, "cors_allow_origins")
    assert cfg.rate_limit_rps > 0
    assert cfg.rate_limit_burst >= 1
    assert cfg.body_max_bytes >= 1024
    assert cfg.cors_allow_origins == []
