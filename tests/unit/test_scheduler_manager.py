"""Tests for scheduler manager (auto-detect)."""

from __future__ import annotations

from unittest.mock import patch


def test_detect_backend_macos() -> None:
    from lazy_harness.scheduler.manager import detect_backend

    with patch("platform.system", return_value="Darwin"):
        backend = detect_backend()
        assert backend.__class__.__name__ == "LaunchdBackend"


def test_detect_backend_linux() -> None:
    from lazy_harness.scheduler.manager import detect_backend

    with patch("platform.system", return_value="Linux"):
        with patch("shutil.which", return_value="/usr/bin/systemctl"):
            backend = detect_backend()
            assert backend.__class__.__name__ == "SystemdBackend"


def test_detect_backend_linux_no_systemd() -> None:
    from lazy_harness.scheduler.manager import detect_backend

    with patch("platform.system", return_value="Linux"):
        with patch("shutil.which", return_value=None):
            backend = detect_backend()
            assert backend.__class__.__name__ == "CronBackend"


def test_parse_jobs_from_config_empty() -> None:
    from lazy_harness.core.config import Config, HarnessConfig, SchedulerConfig
    from lazy_harness.scheduler.manager import parse_jobs_from_config

    cfg = Config(harness=HarnessConfig(version="1"), scheduler=SchedulerConfig(backend="auto"))
    jobs = parse_jobs_from_config(cfg)
    assert jobs == []


def test_parse_jobs_from_config_converts_entries() -> None:
    from lazy_harness.core.config import (
        Config,
        HarnessConfig,
        SchedulerConfig,
        SchedulerJobConfig,
    )
    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.manager import parse_jobs_from_config

    cfg = Config(
        harness=HarnessConfig(version="1"),
        scheduler=SchedulerConfig(
            backend="launchd",
            jobs=[
                SchedulerJobConfig(
                    name="qmd-sync",
                    schedule="*/30 * * * *",
                    command="/usr/local/bin/lh knowledge sync",
                ),
                SchedulerJobConfig(
                    name="qmd-embed",
                    schedule="0 6 * * *",
                    command="/usr/local/bin/lh knowledge embed",
                ),
            ],
        ),
    )

    jobs = parse_jobs_from_config(cfg)
    assert len(jobs) == 2
    assert all(isinstance(j, SchedulerJob) for j in jobs)
    assert jobs[0].name == "qmd-sync"
    assert jobs[0].schedule == "*/30 * * * *"
    assert jobs[1].command.endswith("lh knowledge embed")


def test_detect_backend_passes_the_timezone_to_systemd() -> None:
    from lazy_harness.scheduler.manager import detect_backend
    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = detect_backend("systemd", timezone="America/Argentina/Buenos_Aires")

    assert isinstance(backend, SystemdBackend)
    assert backend._timezone == "America/Argentina/Buenos_Aires"


def test_install_and_drift_agree_on_the_timezone(tmp_path) -> None:
    """The same answer, resolved twice, from one config.

    A caller that builds the backend without the zone renders a bare
    `OnCalendar=` and reports the unit it just wrote as STALE — a drift alarm
    for a difference that exists only between two call sites.
    """
    from lazy_harness.core.config import Config, SchedulerConfig, SchedulerJobConfig
    from lazy_harness.scheduler.base import DriftState
    from lazy_harness.scheduler.manager import detect_backend, parse_jobs_from_config

    cfg = Config()
    cfg.scheduler = SchedulerConfig(
        backend="systemd",
        timezone="America/Argentina/Buenos_Aires",
        jobs=[
            SchedulerJobConfig(
                name="weekly-review", schedule="0 8 * * 1", command="/usr/bin/true"
            )
        ],
    )
    jobs = parse_jobs_from_config(cfg)

    writer = detect_backend(cfg.scheduler.backend, timezone=cfg.scheduler.timezone)
    writer._unit_dir = tmp_path
    writer._runner = lambda argv: __import__("subprocess").CompletedProcess(argv, 0, "", "")
    writer._which = lambda name: "/usr/bin/true"
    writer.install(jobs)

    reader = detect_backend(cfg.scheduler.backend, timezone=cfg.scheduler.timezone)
    reader._unit_dir = tmp_path
    reader._runner = lambda argv: __import__("subprocess").CompletedProcess(argv, 0, "", "")
    reader._which = lambda name: "/usr/bin/true"

    assert [d.state for d in reader.drift(jobs)] == [DriftState.CURRENT]
