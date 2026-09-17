"""Tests for `lh metrics launches`."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.metrics_cmd import metrics
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


def _fixed_clock(db: MetricsDB, monkeypatch: pytest.MonkeyPatch, when: str) -> None:
    ts = datetime.fromisoformat(when).timestamp()
    monkeypatch.setattr(db, "_now", lambda: ts)


def test_reports_counts_grouped_by_profile_agent_entry(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    db = MetricsDB(db_path)
    db.record_launch(profile="lazy", agent="claude-code", entry="run")
    db.record_launch(profile="flex", agent="codex", entry="exec")

    result = CliRunner().invoke(metrics, ["launches", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "lazy" in result.output
    assert "claude-code" in result.output
    assert "flex" in result.output
    assert "codex" in result.output


def test_ratio_block_shows_a_dash_for_an_unmeasured_profile(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    db = MetricsDB(db_path)
    db.record_launch(profile="flex", agent="codex", entry="exec")

    result = CliRunner().invoke(metrics, ["launches", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "flex" in result.output
    assert "—" in result.output  # em dash for ratio=None


def test_ratio_block_shows_the_computed_ratio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "metrics.db"
    db = MetricsDB(db_path)
    _fixed_clock(db, monkeypatch, "2026-09-16T12:00:00")
    for _ in range(3):
        db.record_launch(profile="lazy", agent="claude-code", entry="run")
    db.insert_stats([_stat("s1", "2026-09-10", "lazy"), _stat("s2", "2026-09-12", "lazy")])
    db.close()

    result = CliRunner().invoke(metrics, ["launches", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "1.5" in result.output


def test_days_filters_the_launch_count(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    db = MetricsDB(db_path)
    db._conn.execute(
        "INSERT INTO launches (ts, profile, agent, host, entry) VALUES (?,?,?,?,?)",
        (1000.0, "old", "codex", "", "run"),
    )
    db._conn.commit()
    db.close()

    result = CliRunner().invoke(metrics, ["launches", "--db", str(db_path), "--days", "1"])

    assert result.exit_code == 0
    assert "old" not in result.output


def test_json_flag_emits_null_for_an_unmeasured_ratio(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    db = MetricsDB(db_path)
    db.record_launch(profile="flex", agent="codex", entry="exec")
    db.close()

    result = CliRunner().invoke(metrics, ["launches", "--db", str(db_path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["launches"] == [
        {"profile": "flex", "agent": "codex", "entry": "exec", "count": 1}
    ]
    ratio_entry = next(r for r in payload["ratios"] if r["profile"] == "flex")
    assert ratio_entry["ratio"] is None


def test_runs_on_an_empty_db_without_crashing(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    MetricsDB(db_path)

    result = CliRunner().invoke(metrics, ["launches", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "no launches recorded" in result.output


def test_runs_with_no_parameters_at_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test: the default DB path must resolve without an explicit --db."""
    monkeypatch.setattr("lazy_harness.cli.metrics_cmd.data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "lazy_harness.cli.metrics_cmd.config_file", lambda: tmp_path / "nonexistent.toml"
    )

    result = CliRunner().invoke(metrics, ["launches"])

    assert result.exit_code == 0, result.output
