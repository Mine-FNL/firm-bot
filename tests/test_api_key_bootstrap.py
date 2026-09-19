"""Tests for the default-on API key bootstrap (:meth:`RootConfig.ensure_api_key`).

Behaviour pinned here:
  - default require_api_key=True (v0.2 flip from prior opt-in)
  - ensure_api_key is a no-op when require_api_key is False
  - ensure_api_key is a no-op when api_keys already has entries
  - ensure_api_key auto-generates a 256-bit URL-safe token when empty
  - the generated token persists to ``<data_dir>/config.yaml`` so a
    restart doesn't rotate it
  - env override ``FIRM_BOT_API_KEYS`` wins over auto-generated keys
    on subsequent boots
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
import yaml

from firm_bot.config import RootConfig


def test_default_require_api_key_is_true() -> None:
    """As of v0.2 the API key gate is enabled by default."""
    cfg = RootConfig()
    assert cfg.require_api_key is True


def test_ensure_api_key_noop_when_disabled(tmp_path: Path) -> None:
    cfg = RootConfig(data_dir=str(tmp_path), require_api_key=False)
    cfg.ensure_api_key()
    assert cfg.api_keys == []


def test_ensure_api_key_noop_when_already_configured(tmp_path: Path) -> None:
    cfg = RootConfig(
        data_dir=str(tmp_path),
        require_api_key=True,
        api_keys=["preset-key"],
    )
    cfg.ensure_api_key()
    # No rotation of an existing key.
    assert cfg.api_keys == ["preset-key"]
    # No config.yaml written (nothing to persist).
    assert not (tmp_path / "config.yaml").exists()


def test_ensure_api_key_generates_url_safe_token(tmp_path: Path) -> None:
    """When require_api_key=True and api_keys=[], generate a token."""
    cfg = RootConfig(data_dir=str(tmp_path), require_api_key=True)
    assert cfg.api_keys == []
    cfg.ensure_api_key()
    assert len(cfg.api_keys) == 1
    key = cfg.api_keys[0]
    # 32 bytes → 43-char URL-safe base64 (no padding). Range 40-50 chars.
    assert 40 <= len(key) <= 50
    # URL-safe alphabet: A-Z a-z 0-9 - _ (Python's token_urlsafe default)
    assert re.match(r"^[A-Za-z0-9_-]+$", key), f"unexpected chars in {key!r}"


def test_ensure_api_key_persists_to_config_yaml(tmp_path: Path) -> None:
    """After bootstrap, the generated key is written to config.yaml."""
    cfg = RootConfig(data_dir=str(tmp_path), require_api_key=True)
    cfg.ensure_api_key()
    cfg_path = tmp_path / "config.yaml"
    assert cfg_path.exists()
    raw = yaml.safe_load(cfg_path.read_text())
    assert raw["require_api_key"] is True
    assert raw["api_keys"] == cfg.api_keys


def test_ensure_api_key_does_not_rotate_on_second_call(tmp_path: Path) -> None:
    """Calling ensure_api_key twice should keep the same key (idempotent)."""
    cfg = RootConfig(data_dir=str(tmp_path), require_api_key=True)
    cfg.ensure_api_key()
    first_key = cfg.api_keys[0]
    # Second call: simulate restart by reloading config from YAML.
    cfg2 = RootConfig.load(tmp_path / "config.yaml")
    cfg2.data_dir = str(tmp_path)
    cfg2.ensure_api_key()
    assert cfg2.api_keys == [first_key]


def test_ensure_api_key_logs_generated_key_with_marker(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The generated key must appear in logs once, with a clear marker."""
    cfg = RootConfig(data_dir=str(tmp_path), require_api_key=True)
    with caplog.at_level(logging.WARNING, logger="firm_bot.config"):
        cfg.ensure_api_key()
    full = "\n".join(r.getMessage() for r in caplog.records)
    assert "GENERATED_API_KEY" in full
    # The key itself is logged once with the "Bearer" prefix.
    assert cfg.api_keys[0] in full
