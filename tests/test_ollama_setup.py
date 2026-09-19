"""Tests for firm_bot.ollama_setup — auto-pull on startup."""

from __future__ import annotations

import httpx
import respx

from firm_bot.ollama_setup import (
    ensure_model_pulled,
    is_model_pulled,
    list_models,
    pull_model,
)

HOST = "http://mock-ollama:11434"


def test_list_models_parses_api_tags_response() -> None:
    with respx.mock(base_url=HOST) as mock:
        mock.get("/api/tags").mock(
            return_value=httpx.Response(
                200,
                json={"models": [{"name": "qwen2.5-coder:7b"}, {"name": "nomic-embed-text"}]},
            )
        )
        models = list_models(HOST)
    assert {m["name"] for m in models} == {"qwen2.5-coder:7b", "nomic-embed-text"}


def test_is_model_pulled_matches_exact_name() -> None:
    with respx.mock(base_url=HOST, assert_all_called=False) as mock:
        mock.get("/api/tags").mock(
            return_value=httpx.Response(
                200,
                json={"models": [{"name": "qwen2.5-coder:7b"}]},
            )
        )
        assert is_model_pulled(HOST, "qwen2.5-coder:7b") is True
        assert is_model_pulled(HOST, "qwen2.5-coder:14b") is False


def test_is_model_pulled_matches_bare_name() -> None:
    """`qwen2.5-coder` should match a tag of `qwen2.5-coder:7b`."""
    with respx.mock(base_url=HOST, assert_all_called=False) as mock:
        mock.get("/api/tags").mock(
            return_value=httpx.Response(
                200,
                json={"models": [{"name": "qwen2.5-coder:7b"}]},
            )
        )
        assert is_model_pulled(HOST, "qwen2.5-coder") is True


def test_is_model_pulled_returns_false_on_unreachable_host() -> None:
    """No mock → /api/tags fails → best-effort returns False."""
    assert is_model_pulled("http://does-not-exist:11434", "any-model") is False


def test_pull_model_streams_ndjson_progress() -> None:
    lines = [
        '{"status": "pulling manifest"}',
        '{"status": "downloading", "digest": "sha256:abc", "total": 100, "completed": 50}',
        '{"status": "success"}',
    ]
    body = "\n".join(lines).encode("utf-8")
    with respx.mock(base_url=HOST, assert_all_called=False) as mock:
        mock.post("/api/pull").mock(return_value=httpx.Response(200, content=body))
        events = list(pull_model(HOST, "qwen2.5-coder:7b"))
    assert len(events) == 3
    assert events[-1]["status"] == "success"


def test_ensure_model_pulled_skips_when_already_present() -> None:
    """If the model is already on the server, no /api/pull call is made."""
    with respx.mock(base_url=HOST, assert_all_called=False) as mock:
        tags_route = mock.get("/api/tags").mock(
            return_value=httpx.Response(
                200,
                json={"models": [{"name": "qwen2.5-coder:1.5b-instruct"}]},
            )
        )
        # Register a /api/pull route too so respx doesn't 404 it
        # if our code accidentally calls it — we just want to
        # verify the call_count remains 0.
        pull_route = mock.post("/api/pull").mock(
            return_value=httpx.Response(200, content=b'{"status":"success"}\n')
        )
        ok = ensure_model_pulled(HOST, "qwen2.5-coder:1.5b-instruct")
    assert ok is True
    assert tags_route.call_count == 1
    assert pull_route.call_count == 0


def test_ensure_model_pulled_pulls_when_missing() -> None:
    """If the model is missing, /api/pull is called and success is reported."""
    body = b'{"status":"pulling manifest"}\n{"status":"success"}\n'
    with respx.mock(base_url=HOST, assert_all_called=False) as mock:
        mock.get("/api/tags").mock(return_value=httpx.Response(200, json={"models": []}))
        pull_route = mock.post("/api/pull").mock(return_value=httpx.Response(200, content=body))
        ok = ensure_model_pulled(HOST, "qwen2.5-coder:1.5b-instruct")
    assert ok is True
    assert pull_route.call_count == 1


def test_ensure_model_pulled_swallows_pull_failure() -> None:
    """A failing /api/pull should NOT raise; ensure_model_pulled returns False."""
    with respx.mock(base_url=HOST, assert_all_called=False) as mock:
        mock.get("/api/tags").mock(return_value=httpx.Response(200, json={"models": []}))
        mock.post("/api/pull").mock(return_value=httpx.Response(500, content=b"oops"))
        ok = ensure_model_pulled(HOST, "qwen2.5-coder:1.5b-instruct")
    assert ok is False
