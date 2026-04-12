"""Integration tests for lh status commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    MonitoringConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)


def _setup_config(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    db_path = home_dir / ".local" / "share" / "lazy-harness" / "metrics.db"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(config_dir=str(home_dir / ".claude-personal"), roots=["~"])
            },
        ),
        monitoring=MonitoringConfig(enabled=True, db=str(db_path)),
    )
    save_config(cfg, config_path)
    (home_dir / ".claude-personal").mkdir(parents=True, exist_ok=True)
    return config_path


def test_status_overview(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0


def test_status_costs(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "costs"])
    assert result.exit_code == 0


def test_status_no_monitoring(home_dir: Path) -> None:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        monitoring=MonitoringConfig(enabled=False),
    )
    save_config(cfg, config_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    out = result.output.lower()
    assert "monitoring" in out or "disabled" in out or "enable" in out
