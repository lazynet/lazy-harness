"""Integration tests for lh scheduler commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import Config, HarnessConfig, SchedulerConfig, save_config


def _setup_config(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(harness=HarnessConfig(version="1"), scheduler=SchedulerConfig(backend="auto"))
    save_config(cfg, config_path)
    return config_path


def test_scheduler_status(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["scheduler", "status"])
    assert result.exit_code == 0
    assert "scheduler" in result.output.lower() or "backend" in result.output.lower()


def test_scheduler_install_no_jobs(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["scheduler", "install"])
    assert result.exit_code == 0
    assert "No jobs configured" in result.output


def test_scheduler_uninstall_no_jobs(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["scheduler", "uninstall"])
    assert result.exit_code == 0
    assert "No jobs to remove" in result.output


def test_scheduler_status_missing_config(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["scheduler", "status"])
    assert result.exit_code != 0
    assert "Error" in result.output
