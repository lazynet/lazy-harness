"""Tests for `lh metrics rename-profile`."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.metrics_cmd import metrics
from lazy_harness.monitoring.db import MetricsDB


def _event(**over: object):
    from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent

    base = dict(
        event_id="e1",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="martin",
        tenant_id="local",
        profile="lazy",
        session="s1",
        model="sonnet",
        project="lazy-harness",
        date="2026-08-31",
        input_tokens=10,
        output_tokens=5,
        cache_read=0,
        cache_create=0,
        cost=0.01,
    )
    base.update(over)
    return MetricEvent(**base)  # type: ignore[arg-type]


@pytest.fixture
def config_naming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A config declaring `claude-lazy` — the rename target — and nothing else."""
    lh_config = tmp_path / "lh"
    lh_config.mkdir()
    (lh_config / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "claude-lazy"\n\n'
        f'[profiles.claude-lazy]\nconfig_dir = "{tmp_path / "cfg"}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    return lh_config


def test_rename_profile_renames_and_reports_counts(config_naming: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    db = MetricsDB(db_path)
    db.upsert_event(_event())
    db.close()

    result = CliRunner().invoke(
        metrics, ["rename-profile", "lazy", "claude-lazy", "--db", str(db_path)]
    )

    assert result.exit_code == 0, result.output
    assert "session_stats: 1" in result.output


def test_rename_profile_refuses_an_unconfigured_target(config_naming: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    MetricsDB(db_path).close()

    result = CliRunner().invoke(metrics, ["rename-profile", "lazy", "ghost", "--db", str(db_path)])

    assert result.exit_code != 0
    assert "ghost" in result.output


def test_rename_profile_refuses_old_equals_new(config_naming: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    MetricsDB(db_path).close()

    result = CliRunner().invoke(
        metrics, ["rename-profile", "claude-lazy", "claude-lazy", "--db", str(db_path)]
    )

    assert result.exit_code != 0


def test_rename_profile_is_idempotent_on_the_cli(config_naming: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    db = MetricsDB(db_path)
    db.upsert_event(_event())
    db.close()

    first = CliRunner().invoke(
        metrics, ["rename-profile", "lazy", "claude-lazy", "--db", str(db_path)]
    )
    second = CliRunner().invoke(
        metrics, ["rename-profile", "lazy", "claude-lazy", "--db", str(db_path)]
    )

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "session_stats: 0" in second.output
