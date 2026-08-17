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


def test_scheduler_install_unsupported_backend_fails_loud(home_dir: Path) -> None:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("""
[harness]
version = "1"

[scheduler]
backend = "cron"

[scheduler.jobs.qmd-sync]
schedule = "*/30 * * * *"
command = "lh knowledge sync"
""")
    runner = CliRunner()
    result = runner.invoke(cli, ["scheduler", "install"])
    assert result.exit_code != 0
    assert "Error" in result.output


def test_scheduler_install_reports_an_untranslatable_schedule_without_a_traceback(
    tmp_path, monkeypatch
) -> None:
    """A schedule launchd cannot express must reach the user as an error line.

    The CLI caught only NotImplementedError, so a ScheduleTranslationError
    escaped as a stack trace.
    """
    from click.testing import CliRunner

    from lazy_harness.cli.scheduler_cmd import scheduler
    from lazy_harness.core import paths

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n'
        "[scheduler]\n"
        'backend = "launchd"\n\n'
        "[scheduler.jobs.weekdays]\n"
        'schedule = "0 9 * * 1-5"\n'
        'command = "echo hi"\n'
    )
    monkeypatch.setattr(paths, "config_file", lambda: cfg)
    monkeypatch.setattr("lazy_harness.cli.scheduler_cmd.config_file", lambda: cfg)

    result = CliRunner().invoke(scheduler, ["install"])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "weekdays" in result.output
