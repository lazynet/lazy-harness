"""Detecting scheduled artifacts written by a superseded generator.

An installed plist, unit or crontab entry is a file written once and read for
months. When the code that generates it changes, every already-installed job
keeps the old content, and until now nothing said so: the scheduler check
compared the *number* of declared jobs against the number installed, so a
machine whose jobs were all written by an older version reported PASSED
forever.

This came from a real case — the PATH resolver changed in 0.41.0 and again in
0.41.1, and the only thing that caught the stale plists was reading them by
hand.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

from lazy_harness.scheduler.base import DriftState, SchedulerJob

JOB = SchedulerJob(name="qmd-sync", schedule="0 6 * * *", command="/usr/bin/true sync")


def _quiet(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


# --------------------------------------------------------------------- launchd


def _launchd(tmp_path: Path):
    from lazy_harness.scheduler.launchd import LaunchdBackend

    return LaunchdBackend(agents_dir=tmp_path, runner=_quiet)


def test_launchd_reports_current_for_a_freshly_installed_job(tmp_path: Path) -> None:
    backend = _launchd(tmp_path)
    backend.install([JOB])

    (drift,) = backend.drift([JOB])
    assert drift.name == "qmd-sync"
    assert drift.state is DriftState.CURRENT


def test_launchd_reports_stale_when_the_installed_plist_differs(tmp_path: Path) -> None:
    """The exact shape of the 0.41.0 PATH regression: the job is loaded and
    runs, and its environment is one the current generator would never write."""
    backend = _launchd(tmp_path)
    backend.install([JOB])

    plist_path = tmp_path / "com.lazy-harness.qmd-sync.plist"
    data = plistlib.loads(plist_path.read_bytes())
    data["EnvironmentVariables"]["PATH"] = "/opt/stale/bin"
    plist_path.write_bytes(plistlib.dumps(data))

    (drift,) = backend.drift([JOB])
    assert drift.state is DriftState.STALE
    assert "EnvironmentVariables" in drift.detail


def test_launchd_reports_absent_when_nothing_is_installed(tmp_path: Path) -> None:
    (drift,) = _launchd(tmp_path).drift([JOB])
    assert drift.state is DriftState.ABSENT


def test_launchd_reports_unknown_when_the_job_cannot_be_rendered(tmp_path: Path) -> None:
    """A checker that cannot check must not answer 'current'."""
    backend = _launchd(tmp_path)
    bad = SchedulerJob(name="bad", schedule="0 99 * * *", command="/usr/bin/true")
    (tmp_path / "com.lazy-harness.bad.plist").write_bytes(plistlib.dumps({"Label": "x"}))

    (drift,) = backend.drift([bad])
    assert drift.state is DriftState.UNKNOWN
    assert drift.detail


# --------------------------------------------------------------------- systemd


def _systemd(tmp_path: Path):
    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = SystemdBackend(unit_dir=tmp_path, runner=lambda a: _quiet(a))
    backend._which = lambda name: f"/usr/bin/{name}"  # type: ignore[method-assign]
    return backend


def test_systemd_reports_current_for_a_freshly_installed_job(tmp_path: Path) -> None:
    backend = _systemd(tmp_path)
    backend.install([JOB])

    (drift,) = backend.drift([JOB])
    assert drift.state is DriftState.CURRENT


def test_systemd_reports_stale_when_the_service_text_differs(tmp_path: Path) -> None:
    backend = _systemd(tmp_path)
    backend.install([JOB])

    service = tmp_path / "lazy-harness-qmd-sync.service"
    service.write_text(service.read_text().replace("Environment=", "Environment=X"))

    (drift,) = backend.drift([JOB])
    assert drift.state is DriftState.STALE
    assert "service" in drift.detail


def test_systemd_reports_stale_when_the_timer_text_differs(tmp_path: Path) -> None:
    backend = _systemd(tmp_path)
    backend.install([JOB])

    timer = tmp_path / "lazy-harness-qmd-sync.timer"
    timer.write_text(timer.read_text().replace("OnCalendar=*-*-* 06:00:00", "OnCalendar=hourly"))

    (drift,) = backend.drift([JOB])
    assert drift.state is DriftState.STALE
    assert "timer" in drift.detail


def test_systemd_reports_absent_when_nothing_is_installed(tmp_path: Path) -> None:
    (drift,) = _systemd(tmp_path).drift([JOB])
    assert drift.state is DriftState.ABSENT


# ------------------------------------------------------------------------ cron


class _FakeCrontab:
    def __init__(self, initial: str = "") -> None:
        self.content = initial

    def __call__(self, argv: list[str], *, input: str | None = None):  # noqa: A002
        if argv[1:] == ["-l"]:
            if not self.content:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no crontab")
            return subprocess.CompletedProcess(argv, 0, stdout=self.content, stderr="")
        self.content = input or ""
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def test_cron_reports_current_for_a_freshly_installed_job() -> None:
    from lazy_harness.scheduler.cron import CronBackend

    fake = _FakeCrontab()
    backend = CronBackend(runner=fake)
    backend.install([JOB])

    (drift,) = backend.drift([JOB])
    assert drift.state is DriftState.CURRENT


def test_cron_reports_stale_when_the_block_path_differs() -> None:
    """PATH is written once for the whole block, so a job whose own entry is
    untouched still runs with an environment the generator would not write."""
    from lazy_harness.scheduler.cron import CronBackend
    from lazy_harness.scheduler.paths import resolved_path

    fake = _FakeCrontab()
    backend = CronBackend(runner=fake)
    backend.install([JOB])
    fake.content = fake.content.replace(f"PATH={resolved_path()}", "PATH=/opt/stale/bin")

    (drift,) = backend.drift([JOB])
    assert drift.state is DriftState.STALE
    assert "PATH" in drift.detail


def test_cron_reports_stale_when_the_entry_line_differs() -> None:
    from lazy_harness.scheduler.cron import CronBackend

    fake = _FakeCrontab()
    backend = CronBackend(runner=fake)
    backend.install([JOB])
    fake.content = fake.content.replace("0 6 * * *", "0 7 * * *")

    (drift,) = backend.drift([JOB])
    assert drift.state is DriftState.STALE


def test_cron_reports_absent_when_nothing_is_installed() -> None:
    from lazy_harness.scheduler.cron import CronBackend

    (drift,) = CronBackend(runner=_FakeCrontab()).drift([JOB])
    assert drift.state is DriftState.ABSENT


def test_cron_reports_unknown_when_the_crontab_is_unreachable() -> None:
    from lazy_harness.scheduler.cron import CronBackend

    def missing(argv, *, input=None):  # noqa: A002, ANN001
        raise FileNotFoundError("crontab")

    (drift,) = CronBackend(runner=missing).drift([JOB])
    assert drift.state is DriftState.UNKNOWN
    assert "crontab" in drift.detail
