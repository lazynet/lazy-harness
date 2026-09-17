"""Integration tests for the `Launches` block in `lh doctor`.

Mirrors tests/cli/test_doctor_sink_freshness.py: `lh doctor` never creates a
metrics DB that does not already exist, so the smoke test asserts that too.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli import doctor_cmd
from lazy_harness.cli.doctor_cmd import doctor
from lazy_harness.monitoring.db import MetricsDB


def _stat(session: str, date: str, profile: str) -> dict[str, object]:
    return {
        "session": session,
        "date": date,
        "model": "claude-opus-4-6",
        "profile": profile,
        "project": "p",
        "input": 1,
        "output": 1,
        "cache_read": 0,
        "cache_create": 0,
        "cost": 0.0,
    }


def _write_config(tmp_path: Path, db_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        f'[harness]\nversion = "1"\n[monitoring]\nenabled = true\ndb = "{db_path.as_posix()}"\n'
    )


def test_doctor_reports_none_and_never_creates_a_missing_db(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "nonexistent.db"
    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

    result = CliRunner().invoke(doctor)

    assert "Launches" in result.output
    assert "none" in result.output
    assert not db_path.exists()
    assert result.exit_code == 0


def test_doctor_lists_non_claude_profiles_and_shows_horizon_opens_before_it_elapses(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    db.record_launch(profile="flex", agent="codex", entry="exec")
    db.close()
    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

    result = CliRunner().invoke(doctor)

    assert "flex" in result.output
    assert "horizon opens 2026-11-11" in result.output
    assert result.exit_code == 0


def test_doctor_reports_horizon_not_started_when_uncalibrated(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    db.record_launch(profile="flex", agent="codex", entry="exec")
    db.close()
    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 12, 1, tzinfo=UTC))

    result = CliRunner().invoke(doctor)

    assert "horizon not started: launch-to-session ratio unmeasured" in result.output
    assert result.exit_code == 0


def test_doctor_names_the_profile_below_threshold_once_calibrated(
    tmp_path: Path, monkeypatch
) -> None:
    frozen_dt = datetime(2026, 12, 1, 12, tzinfo=UTC)
    monkeypatch.setattr(MetricsDB, "_now", lambda self: frozen_dt.timestamp())

    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    for _ in range(10):
        db.record_launch(profile="lazy", agent="claude-code", entry="run")
    db.insert_stats([_stat(f"s{i}", "2026-11-20", "lazy") for i in range(5)])
    for _ in range(9):
        db.record_launch(profile="flex", agent="codex", entry="exec")
    db.close()

    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: frozen_dt)

    result = CliRunner().invoke(doctor)

    assert "flex" in result.output
    assert "below threshold" in result.output
    assert result.exit_code == 0
