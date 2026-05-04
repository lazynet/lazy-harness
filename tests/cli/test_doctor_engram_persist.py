"""Integration tests for the `Engram persist` block in `lh doctor`."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.doctor_cmd import doctor


def _write_run(
    logs_dir: Path,
    *,
    when: datetime,
    saved_ok: int = 1,
    saved_failed: int = 0,
    cursor_lag_bytes: dict[str, int] | None = None,
) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": "run",
        "duration_ms": 100,
        "subprocess_ms": 80,
        "entries_seen": {"decisions": saved_ok, "failures": 0},
        "saved_ok": saved_ok,
        "saved_failed": saved_failed,
        "skipped_malformed": 0,
        "cursor_lag_bytes": cursor_lag_bytes or {"decisions": 0, "failures": 0},
        "project_key": "lazy-harness",
        "engram_version": "1.15.6",
        "hook_version": "0.16.0",
    }
    (logs_dir / "engram_persist_metrics.jsonl").write_text(json.dumps(payload) + "\n")


@pytest.fixture
def lh_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))
    return claude_dir


def test_doctor_shows_engram_persist_block_header(lh_env: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "Engram persist" in result.output


def test_doctor_reports_missing_when_metrics_file_absent(lh_env: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "Engram persist" in result.output
    assert "no runs yet" in result.output.lower()
    assert result.exit_code == 0


def test_doctor_reports_ok_for_fresh_clean_run(lh_env: Path) -> None:
    now = datetime.now(UTC)
    _write_run(lh_env / "logs", when=now - timedelta(minutes=5))

    runner = CliRunner()
    result = runner.invoke(doctor)

    output = result.output
    assert "Engram persist" in output
    assert "Last run" in output
    assert "Failure rate" in output
    assert "Cursor lag" in output
    assert result.exit_code == 0


def test_doctor_fails_when_engram_persist_block_fails(lh_env: Path) -> None:
    stale = datetime.now(UTC) - timedelta(days=10)
    _write_run(lh_env / "logs", when=stale)

    runner = CliRunner()
    result = runner.invoke(doctor)

    assert result.exit_code == 1
    assert "Engram persist" in result.output
