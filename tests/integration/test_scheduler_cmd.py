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


def test_scheduler_install_on_cron_reports_the_installed_jobs(
    home_dir: Path, monkeypatch
) -> None:
    """The cron backend installs rather than raising, as of this wave.

    Replaces `test_scheduler_install_unsupported_backend_fails_loud`, whose
    premise — that cron is a stub — no longer holds. That test also reached
    the real `crontab`, which is global to the user and unaffected by the
    redirected `$HOME`, so running the suite installed a live cron entry on
    the developer's machine. The runner is injected here for that reason.
    """
    import subprocess

    from lazy_harness.scheduler.cron import CronBackend

    written: list[str] = []

    def fake_crontab(argv, *, input=None):  # noqa: A002, ANN001
        if argv[1:] == ["-l"]:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no crontab")
        written.append(input or "")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "lazy_harness.scheduler.manager.CronBackend",
        lambda: CronBackend(runner=fake_crontab),
    )

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
    result = CliRunner().invoke(cli, ["scheduler", "install"])

    assert result.exit_code == 0, result.output
    assert "lazy-harness-qmd-sync" in result.output
    assert "# lazy-harness:qmd-sync" in written[-1]


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


def test_scheduler_install_reports_a_backend_failure_without_a_traceback(
    home_dir: Path, monkeypatch
) -> None:
    """A machine without `crontab` is the documented cron-fallback target.

    The CLI caught NotImplementedError and ScheduleTranslationError only, so
    CronBackend's RuntimeError escaped as a stack trace.
    """
    from lazy_harness.scheduler.cron import CronBackend

    def no_crontab(argv, *, input=None):  # noqa: A002, ANN001
        raise FileNotFoundError("crontab")

    monkeypatch.setattr(
        "lazy_harness.scheduler.manager.CronBackend",
        lambda: CronBackend(runner=no_crontab),
    )

    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("""
[harness]
version = "1"

[scheduler]
backend = "cron"

[scheduler.jobs.x]
schedule = "0 6 * * *"
command = "true"
""")
    result = CliRunner().invoke(cli, ["scheduler", "install"])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "crontab" in result.output


def test_config_error_keeps_the_section_name_it_exists_to_report(home_dir: Path) -> None:
    """`console.print(f"[red]Error: {e}[/red]")` hands the message to rich as
    markup, so a `[section]` inside it is parsed as a tag and deleted.

    `Missing [harness].version` reached the terminal as `Missing .version` —
    the message loses precisely the identifier it was written to name.
    """
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text('[scheduler]\nbackend = "auto"\n')

    result = CliRunner().invoke(cli, ["scheduler", "status"])

    assert result.exit_code != 0
    assert "[harness].version" in result.output, result.output


def test_the_no_jobs_hint_names_the_table_to_add(home_dir: Path) -> None:
    """Same failure in a literal string: the hint told the user to configure
    jobs `under` and then stopped, because rich ate the table name."""
    _setup_config(home_dir)

    result = CliRunner().invoke(cli, ["scheduler", "status"])

    assert result.exit_code == 0
    assert "[scheduler.jobs]" in result.output, result.output


def test_scheduler_install_carries_the_configured_timezone(home_dir: Path, monkeypatch) -> None:
    """`lh scheduler install` is the only writer that matters.

    The renderer and the backend both accepting a zone proves nothing while
    the CLI builds its backend without one: the field loads, validates, and
    changes nothing on disk.
    """
    from lazy_harness.core.config import SchedulerJobConfig

    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        scheduler=SchedulerConfig(
            backend="systemd",
            timezone="America/Argentina/Buenos_Aires",
            jobs=[
                SchedulerJobConfig(
                    name="weekly-review", schedule="0 8 * * 1", command="/usr/bin/true"
                )
            ],
        ),
    )
    save_config(cfg, config_path)

    unit_dir = home_dir / ".config" / "systemd" / "user"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home_dir / ".config"))
    monkeypatch.setattr(
        "lazy_harness.scheduler.systemd.SystemdBackend._which", lambda self, name: "/usr/bin/true"
    )
    monkeypatch.setattr(
        "lazy_harness.scheduler.systemd._default_runner",
        lambda argv: __import__("subprocess").CompletedProcess(argv, 0, "Linger=yes", ""),
    )

    result = CliRunner().invoke(cli, ["scheduler", "install"])

    assert result.exit_code == 0, result.output
    timer = (unit_dir / "lazy-harness-weekly-review.timer").read_text()
    assert "OnCalendar=Mon *-*-* 08:00:00 America/Argentina/Buenos_Aires" in timer
