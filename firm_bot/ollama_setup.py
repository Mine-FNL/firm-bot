"""One-shot Ollama model bootstrap.

Removes the "ollama pull X" step from the user-facing quickstart:

  firm-bot serve    # auto-pulls default model if missing

This is purely a convenience — users who want to control the model
fetch separately can set `FIRM_BOT_AUTO_PULL_MODEL=0` to disable it.
For docker-compose users, this is what makes
`docker compose up -d && curl ...` work on first boot.

The pull is best-effort: if the Ollama daemon is unreachable, we log
a warning but don't fail startup. The query path surfaces the real
error when the user asks a question, so this is safe.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx

log = logging.getLogger("firm_bot.ollama_setup")


def list_models(host: str, timeout_s: float = 5.0) -> list[dict[str, Any]]:
    """GET /api/tags → list of installed models on the Ollama server."""
    with httpx.Client(timeout=timeout_s) as client:
        r = client.get(f"{host.rstrip('/')}/api/tags")
        r.raise_for_status()
        return list(r.json().get("models", []))


def is_model_pulled(host: str, model: str, timeout_s: float = 5.0) -> bool:
    """True if `model` is already present on the Ollama server.

    Matching rules:
      - Exact match: ``qwen2.5-coder:7b`` == ``qwen2.5-coder:7b`` → True
      - Bare request (``qwen2.5-coder``) → matches any installed model
        in the same family (with or without a tag)
      - Tagged request (``qwen2.5-coder:14b``) → matches an installed
        model with the same tag, or a bare-name entry (treated as
        "latest" by most Ollama installs)

    This is intentionally conservative: a tagged request will NOT
    match a different tag of the same family (so ``qwen2.5-coder:7b``
    installed does not satisfy a ``qwen2.5-coder:14b`` request).
    """
    try:
        installed = list_models(host, timeout_s)
    except Exception as e:  # pragma: no cover - best-effort probe
        log.warning("could not list ollama models at %s: %s", host, e)
        return False

    req_has_tag = ":" in model
    req_family = model.split(":", maxsplit=1)[0]
    req_tag = model.split(":", maxsplit=1)[1] if req_has_tag else ""
    for m in installed:
        name: str = m.get("name") or m.get("model") or ""
        if name == model:
            return True
        inst_has_tag = ":" in name
        inst_family = name.split(":", maxsplit=1)[0]
        inst_tag = name.split(":", maxsplit=1)[1] if inst_has_tag else ""
        if not req_has_tag and inst_family == req_family:
            return True
        if req_has_tag and inst_family == req_family and (inst_tag == req_tag or not inst_has_tag):
            return True
    return False


def pull_model(
    host: str,
    model: str,
    timeout_s: float = 1800.0,
) -> Iterator[dict[str, Any]]:
    """POST /api/pull and stream NDJSON progress events.

    Yields each parsed line as a dict. Callers should iterate and look
    for `{"status": "success"}` as the terminal event.

    30 min timeout by default — large models (70B) can take that long
    on slow networks.
    """
    payload = {"name": model, "stream": True}
    with (
        httpx.Client(timeout=timeout_s) as client,
        client.stream("POST", f"{host.rstrip('/')}/api/pull", json=payload) as r,
    ):
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                # Some Ollama builds occasionally emit blank or
                # non-JSON keepalive bytes; ignore them.
                continue


def ensure_model_pulled(
    host: str,
    model: str,
    timeout_s: float = 1800.0,
) -> bool:
    """Pull `model` if not already present on the Ollama server.

    Returns True on success (model present after the call), False if
    the pull failed. Best-effort: any exception is logged and
    swallowed so this never breaks startup.
    """
    if is_model_pulled(host, model):
        log.info("ollama model %s already present", model)
        return True
    log.info("pulling ollama model %s (this may take a few minutes)...", model)
    try:
        for event in pull_model(host, model, timeout_s=timeout_s):
            status = event.get("status", "")
            if status:
                # Don't log every line — only phase transitions.
                log.info("ollama pull: %s", status)
            if status == "success":
                log.info("ollama model %s pulled successfully", model)
                return True
        log.warning("ollama pull stream ended without success status")
        return False
    except Exception as e:
        log.warning("ollama pull for %s failed: %s", model, e)
        return False
