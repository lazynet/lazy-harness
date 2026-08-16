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
    db.record_loop_event(session="s2", kind="goal_absent")
    db.record_loop_event(session="s3", kind="goal_absent")


def test_reports_counts_and_declared_rate(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    _seed(db_path)

    result = CliRunner().invoke(metrics, ["loops", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "goal_declared" in result.output
    assert "33" in result.output, "expected a 33% declared rate (1 of 3)"


def test_reports_zero_rate_without_dividing_by_zero(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    MetricsDB(db_path)

    result = CliRunner().invoke(metrics, ["loops", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "0" in result.output


def test_runs_with_no_parameters_at_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test: the default DB path must resolve without an explicit --db."""
    monkeypatch.setattr("lazy_harness.cli.metrics_cmd.data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "lazy_harness.cli.metrics_cmd.config_file", lambda: tmp_path / "nonexistent.toml"
    )

    result = CliRunner().invoke(metrics, ["loops"])

    assert result.exit_code == 0, result.output
