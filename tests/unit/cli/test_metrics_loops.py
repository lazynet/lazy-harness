"""Tests for `lh metrics loops`."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.metrics_cmd import metrics
from lazy_harness.monitoring.db import MetricsDB


def _seed(db_path: Path) -> None:
    db = MetricsDB(db_path)
    db.record_loop_event(session="s1", kind="goal_declared")
    db.record_loop_event(session="s2", kind="nontrivial_prompt")
    db.record_loop_event(session="s3", kind="nontrivial_prompt")


def test_reports_per_kind_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    _seed(db_path)

    result = CliRunner().invoke(metrics, ["loops", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "goal_declared" in result.output
    assert "nontrivial_prompt" in result.output


def test_prints_the_declared_rate_from_goal_declared_and_goal_absent(tmp_path: Path) -> None:
    """The compound-loop worker now emits goal_declared/goal_absent, so the
    rate is computable: declared / (declared + absent)."""
    db_path = tmp_path / "metrics.db"
    db = MetricsDB(db_path)
    db.record_loop_event(session="s1", kind="goal_declared")
    db.record_loop_event(session="s2", kind="goal_absent")
    db.record_loop_event(session="s3", kind="goal_absent")

    result = CliRunner().invoke(metrics, ["loops", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "goal_declared" in result.output
    assert "declared rate: 33% (1/3)" in result.output


def test_prints_a_zero_percent_rate_without_a_zero_division(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    db = MetricsDB(db_path)
    db.record_loop_event(session="s1", kind="goal_absent")
    db.record_loop_event(session="s2", kind="goal_absent")

    result = CliRunner().invoke(metrics, ["loops", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "declared rate: 0% (0/2)" in result.output


def test_runs_on_an_empty_db_without_crashing(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    MetricsDB(db_path)

    result = CliRunner().invoke(metrics, ["loops", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "declared rate: 0% (0/0)" in result.output


def test_days_filters_out_events_older_than_the_window(tmp_path: Path) -> None:
    """MINOR 2: time.time() - days * 86400 is unexercised arithmetic on a
    user-facing flag; lock in that --days actually filters, and in the
    expected direction."""
    import time

    db_path = tmp_path / "metrics.db"
    db = MetricsDB(db_path)
    now = time.time()
    db._conn.execute(
        "INSERT INTO loop_events (session, ts, project, profile, kind, detail) "
        "VALUES (?, ?, '', '', ?, '')",
        ("old", now - 10 * 86400, "goal_declared"),
    )
    db._conn.execute(
        "INSERT INTO loop_events (session, ts, project, profile, kind, detail) "
        "VALUES (?, ?, '', '', ?, '')",
        ("recent", now - 1 * 86400, "nontrivial_prompt"),
    )
    db._conn.commit()

    result = CliRunner().invoke(metrics, ["loops", "--db", str(db_path), "--days", "5"])

    assert result.exit_code == 0
    assert "nontrivial_prompt" in result.output
    assert "goal_declared" not in result.output


def test_runs_with_no_parameters_at_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test: the default DB path must resolve without an explicit --db."""
    monkeypatch.setattr("lazy_harness.cli.metrics_cmd.data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "lazy_harness.cli.metrics_cmd.config_file", lambda: tmp_path / "nonexistent.toml"
    )

    result = CliRunner().invoke(metrics, ["loops"])

    assert result.exit_code == 0, result.output
