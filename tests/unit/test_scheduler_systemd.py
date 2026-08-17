"""Tests for the systemd user-timer backend."""

from __future__ import annotations

import subprocess
from pathlib import Path

from lazy_harness.scheduler.base import JobState, SchedulerJob


def _runner(script=None, record=None):
    def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        if record is not None:
            record.append(argv)
        out = script(argv) if script else ""
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    return run


def test_install_writes_a_service_and_a_timer(tmp_path: Path) -> None:
    from lazy_harness.scheduler.systemd import SystemdBackend

    calls: list[list[str]] = []
    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=yes", calls))
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 */6 * * *", command="qmd sync")])

    service = (tmp_path / "lazy-harness-qmd-sync.service").read_text()
    timer = (tmp_path / "lazy-harness-qmd-sync.timer").read_text()

    assert "Type=oneshot" in service
    assert "ExecStart=qmd sync" in service
    assert "Environment=PATH=" in service
    assert "OnCalendar=*-*-* 0/6:00:00" in timer
    # A missed run fires on next boot, which is the closest analogue to
    # launchd's catch-up and matters on a workstation that sleeps.
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer

    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert ["systemctl", "--user", "enable", "--now", "lazy-harness-qmd-sync.timer"] in calls


def test_install_validates_every_job_before_writing_any(tmp_path: Path) -> None:
    """One untranslatable job must not leave a half-installed set."""
    import pytest

    from lazy_harness.scheduler.schedule import ScheduleTranslationError
    from lazy_harness.scheduler.systemd import SystemdBackend

    calls: list[list[str]] = []
    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=yes", calls))
    with pytest.raises(ScheduleTranslationError, match="bad"):
        backend.install(
            [
                SchedulerJob(name="good", schedule="0 6 * * *", command="a"),
                SchedulerJob(name="bad", schedule="0 99 * * *", command="b"),
            ]
        )

    assert list(tmp_path.iterdir()) == []
    assert calls == []


def test_install_warns_when_lingering_is_disabled(tmp_path: Path, capsys) -> None:
    """Without linger, user timers stop at logout and never fire on a headless box.

    `systemctl --user enable --now` still reports success, which is exactly
    why this has to be checked rather than assumed.
    """
    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=no"))
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 3 * * *", command="qmd sync")])

    out = capsys.readouterr().out
    assert "enable-linger" in out


def test_install_is_quiet_when_lingering_is_enabled(tmp_path: Path, capsys) -> None:
    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=yes"))
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 3 * * *", command="qmd sync")])

    assert "enable-linger" not in capsys.readouterr().out


def test_uninstall_disables_and_removes_both_unit_files(tmp_path: Path) -> None:
    from lazy_harness.scheduler.systemd import SystemdBackend

    calls: list[list[str]] = []
    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=yes", calls))
    job = SchedulerJob(name="qmd-sync", schedule="0 6 * * *", command="qmd sync")
    backend.install([job])
    calls.clear()

    removed = backend.uninstall([job])

    assert removed == ["lazy-harness-qmd-sync"]
    assert list(tmp_path.iterdir()) == []
    assert ["systemctl", "--user", "disable", "--now", "lazy-harness-qmd-sync.timer"] in calls


def test_job_state_reads_is_active(tmp_path: Path) -> None:
    from lazy_harness.scheduler.systemd import SystemdBackend

    active = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "active\n"))
    assert active.job_state("lazy-harness-x")[0] is JobState.LOADED

    inactive = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "inactive\n"))
    assert inactive.job_state("lazy-harness-x")[0] is JobState.NOT_LOADED


def test_job_state_is_unknown_when_systemctl_is_absent(tmp_path: Path) -> None:
    """A missing systemctl is 'cannot check', not 'not loaded'."""
    from lazy_harness.scheduler.systemd import SystemdBackend

    def missing(argv: list[str]):
        raise FileNotFoundError(argv[0])

    backend = SystemdBackend(unit_dir=tmp_path, runner=missing)
    state, detail = backend.job_state("lazy-harness-x")
    assert state is JobState.UNKNOWN
    assert "systemctl" in detail


def test_discover_reports_installed_timers(tmp_path: Path) -> None:
    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=yes"))
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 */6 * * *", command="qmd sync")])

    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "active\n"))
    records = backend.discover()

    assert [r.name for r in records] == ["qmd-sync"]
    assert records[0].schedule == "*-*-* 0/6:00:00"
    assert records[0].state is JobState.LOADED


def test_systemd_backend_constructs_without_arguments() -> None:
    """Paired smoke test: always injecting leaves default resolution untested."""
    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = SystemdBackend()
    assert backend._unit_dir.parts[-2:] == ("systemd", "user")
    assert backend._runner is not None
