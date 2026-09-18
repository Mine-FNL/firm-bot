"""Tests for `firm-bot demo init` — bundled sample firm bootstrap."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES = REPO_ROOT / "examples" / "sample_data"


def _run_demo(args: list[str], data_dir: Path) -> subprocess.CompletedProcess:
    """Invoke `python -m firm_bot.cli demo init …` with --data-dir override."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "firm_bot.cli",
            "--data-dir",
            str(data_dir),
            "demo",
            "init",
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture
def fresh_data_dir(tmp_path: Path) -> Path:
    """A clean data dir; auto-cleaned at test end."""
    d = tmp_path / "demo-data"
    d.mkdir()
    yield d


def test_samples_exist_on_disk() -> None:
    """Sanity: the bundled samples haven't been deleted."""
    assert SAMPLES.is_dir(), f"missing samples dir: {SAMPLES}"
    pdfs = list(SAMPLES.glob("*.pdf"))
    assert len(pdfs) >= 2, f"expected at least 2 sample PDFs, found {len(pdfs)}"


def _last_json_object(s: str) -> dict:
    """Parse the final JSON object from `s`, ignoring any noise around it.

    `firm-bot demo init` prints human-readable lines ("created firm …",
    "copied 2 sample(s): …") plus HuggingFace warning lines on stderr,
    plus the ingest JSON, plus a summary JSON. Tests just want the
    summary; find the last `{...}` block on the final stdout stream.
    """
    # Find every `{...}` block candidate and try to parse each as JSON.
    # Last one wins; this is robust to surrounding text.
    candidates: list[str] = []
    depth = 0
    start: int | None = None
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(s[start : i + 1])
                start = None
    for block in reversed(candidates):
        try:
            obj = json.loads(block)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"no JSON object found in stdout:\n{s}")


def test_demo_init_creates_firm_and_copies_samples(fresh_data_dir: Path) -> None:
    r = _run_demo([], fresh_data_dir)
    assert r.returncode == 0, f"stderr: {r.stderr}"

    # firm config exists
    firm_dir = fresh_data_dir / "firms" / "demo"
    assert (firm_dir / "config.yaml").exists()

    # samples copied into source/
    source_dir = firm_dir / "source"
    assert source_dir.is_dir()
    pdfs = sorted(p.name for p in source_dir.glob("*.pdf"))
    assert "acme_msa.pdf" in pdfs
    assert "nda.pdf" in pdfs

    # summary block is the last JSON object on stdout
    summary = _last_json_object(r.stdout)
    assert summary["chunks_indexed"] >= 1, f"no chunks indexed; stdout={r.stdout}"
    assert "ready_for" in summary


def test_demo_init_is_idempotent(fresh_data_dir: Path) -> None:
    """Re-running over an existing firm should not error or duplicate."""
    first = _run_demo([], fresh_data_dir)
    assert first.returncode == 0, first.stderr

    second = _run_demo([], fresh_data_dir)
    assert second.returncode == 0, second.stderr

    # source/ should still have exactly the bundled samples, not
    # duplicate copies from the second run.
    source_dir = fresh_data_dir / "firms" / "demo" / "source"
    pdfs = sorted(p.name for p in source_dir.glob("*.pdf"))
    assert pdfs == ["acme_msa.pdf", "nda.pdf"], pdfs


def test_demo_init_reset_wipes_and_recreates(fresh_data_dir: Path) -> None:
    """`--reset` deletes the existing firm directory before re-creating."""
    _run_demo([], fresh_data_dir)
    firm_dir = fresh_data_dir / "firms" / "demo"
    # Drop a sentinel file into the firm dir to confirm --reset wipes it.
    sentinel = firm_dir / "SENTINEL"
    sentinel.write_text("must be removed by --reset")

    r = _run_demo(["--reset"], fresh_data_dir)
    assert r.returncode == 0, r.stderr
    assert not sentinel.exists(), "--reset did not wipe the firm directory"


def test_demo_init_custom_slug_and_name(fresh_data_dir: Path) -> None:
    """`--slug` and `--name` flow through to the new firm."""
    r = _run_demo(["--slug", "acme", "--name", "Acme LLP"], fresh_data_dir)
    assert r.returncode == 0, r.stderr
    cfg = fresh_data_dir / "firms" / "acme" / "config.yaml"
    assert cfg.exists()
    text = cfg.read_text()
    assert "acme" in text
    assert "Acme LLP" in text


def test_demo_init_missing_samples_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """If examples/sample_data is gone, demo init fails fast with a clear error."""
    # Simulate the missing-samples case by passing a non-existent
    # samples dir via env override. Easiest: rename via monkeypatch.
    real_samples = REPO_ROOT / "examples" / "sample_data"
    backup = REPO_ROOT / "examples" / "_sample_data_backup_for_test"
    real_samples.rename(backup)
    try:
        r = subprocess.run(
            [sys.executable, "-m", "firm_bot.cli", "--data-dir", str(tmp_path), "demo", "init"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(REPO_ROOT),
        )
        assert r.returncode != 0
        assert "sample data not found" in r.stderr.lower()
    finally:
        backup.rename(real_samples)
