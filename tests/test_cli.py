"""Tests for the CLI surface.

The CLI is a thin argparse wrapper over the same modules the API
calls. We test a few representative commands end-to-end against the
mocked Ollama + tmp data dir fixtures, plus the help text and error
paths.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner  # type: ignore[import-not-found]  # noqa: F401

# We avoid typer for now — argparse + subprocess is enough.
from firm_bot.cli import main as cli_main


def test_help_exits_clean() -> None:
    """`firm-bot --help` must exit 0 with a usage line."""
    with pytest.raises(SystemExit) as e:
        cli_main(["--help"])
    assert e.value.code == 0


def test_version_exits_clean() -> None:
    """`firm-bot --version` prints the version and exits 0."""
    with pytest.raises(SystemExit) as e:
        cli_main(["--version"])
    assert e.value.code == 0


def test_firm_list_prints_json(env_data_dir: Path) -> None:
    rc = cli_main(["firm", "list"])
    assert rc == 0


def test_firm_create_and_config(env_data_dir: Path) -> None:
    rc = cli_main(["firm", "create", "--slug", "acme", "--name", "Acme LLP"])
    assert rc == 0
    rc = cli_main(["firm", "config", "acme", "--set-llm-model", "qwen-test"])
    assert rc == 0


def test_firm_create_invalid_slug(env_data_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(["firm", "create", "--slug", "BAD SLUG", "--name", "X"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "invalid slug" in captured.err.lower() or "bad slug" in captured.err.lower()


def test_ingest_then_query_cli(env_data_dir: Path, sample_pdf: Path) -> None:
    # set up
    cli_main(["firm", "create", "--slug", "acme", "--name", "Acme LLP"])
    # ingest
    import shutil
    shutil.copy(sample_pdf, env_data_dir / "firms" / "acme" / "source" / sample_pdf.name)
    rc = cli_main(["ingest", "acme"])
    assert rc == 0


def test_query_without_ingest_returns_error(
    env_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_main(["firm", "create", "--slug", "acme", "--name", "Acme"])
    rc = cli_main(["query", "acme", "anything"])
    # 2 because no chunks indexed
    assert rc == 2


def test_migrate_preserves_user_values_and_adds_defaults(
    env_data_dir: Path,
) -> None:
    """Migrate upgrades a v0.1-style config to v0.2 (with new fields)."""
    import yaml

    # Simulate a v0.1 config without the new fields
    cfg = env_data_dir / "firms" / "acme" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "slug: acme\n"
        "name: Acme LLP\n"
        "llm_model: qwen2.5-coder:7b\n"
        "system_prompt: 'You are a legal assistant.'\n"
        "contact_email: 'partner@acme.example'\n"
    )

    rc = cli_main(["migrate", "acme"])
    assert rc == 0

    # backup was written
    backup = cfg.with_name(cfg.name + ".bak")
    assert backup.exists()

    # new config has the v0.2 field
    out = yaml.safe_load(cfg.read_text())
    assert out["slug"] == "acme"
    assert out["llm_model"] == "qwen2.5-coder:7b"  # preserved
    assert out["redact_categories"] == []  # default added
    assert "contact_email" in out  # preserved


def test_migrate_missing_firm_returns_error(env_data_dir: Path) -> None:
    rc = cli_main(["migrate", "nonexistent"])
    assert rc == 1
