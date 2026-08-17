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
    backend._which = lambda name: f"/usr/bin/{name}"  # type: ignore[method-assign]
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 */6 * * *", command="qmd sync")])

    service = (tmp_path / "lazy-harness-qmd-sync.service").read_text()
    timer = (tmp_path / "lazy-harness-qmd-sync.timer").read_text()

    assert "Type=oneshot" in service
    assert "ExecStart=/usr/bin/qmd sync" in service
    assert 'Environment="PATH=' in service
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
    backend._which = lambda name: f"/usr/bin/{name}"  # type: ignore[method-assign]
    with pytest.raises(ScheduleTranslationError, match="bad"):
        backend.install(
            [
                SchedulerJob(name="good", schedule="0 6 * * *", command="true"),
                SchedulerJob(name="bad", schedule="0 99 * * *", command="true"),
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
    backend._which = lambda name: f"/usr/bin/{name}"  # type: ignore[method-assign]
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 3 * * *", command="qmd sync")])

    out = capsys.readouterr().out
    assert "enable-linger" in out


def test_install_is_quiet_when_lingering_is_enabled(tmp_path: Path, capsys) -> None:
    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=yes"))
    backend._which = lambda name: f"/usr/bin/{name}"  # type: ignore[method-assign]
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 3 * * *", command="qmd sync")])

    assert "enable-linger" not in capsys.readouterr().out


def test_uninstall_disables_and_removes_both_unit_files(tmp_path: Path) -> None:
    from lazy_harness.scheduler.systemd import SystemdBackend

    calls: list[list[str]] = []
    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=yes", calls))
    # Inject the resolver: without it this reads the host's PATH, so the test
    # passed on a machine with `qmd` installed and failed on CI.
    backend._which = lambda name: f"/usr/bin/{name}"  # type: ignore[method-assign]
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
    backend._which = lambda name: f"/usr/bin/{name}"  # type: ignore[method-assign]
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


def test_exec_start_resolves_the_command_to_an_absolute_path(tmp_path: Path) -> None:
    """systemd resolves a bare name against a compiled-in list, NOT Environment=PATH.

    The documented example is `command = "lh knowledge sync"`. Written
    verbatim, that unit fails with status=203/EXEC every window while the
    Environment=PATH line right below it makes it look handled.
    """
    from lazy_harness.scheduler.systemd import SystemdBackend

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "lh"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)

    backend = SystemdBackend(unit_dir=tmp_path / "units", runner=_runner(lambda a: "Linger=yes"))
    backend._which = lambda name: str(exe) if name == "lh" else None  # type: ignore[method-assign]

    job = SchedulerJob(name="x", schedule="0 6 * * *", command="lh knowledge sync")
    text = backend._service_text(job)
    assert f"ExecStart={exe} knowledge sync" in text


def test_install_refuses_a_command_it_cannot_resolve(tmp_path: Path) -> None:
    """Better to refuse than to write a unit that fails 203/EXEC forever."""
    import pytest

    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=yes"))
    backend._which = lambda name: None  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="definitely-not-on-path"):
        backend.install(
            [SchedulerJob(name="x", schedule="0 6 * * *", command="definitely-not-on-path run")]
        )
    assert list(tmp_path.iterdir()) == []


def test_install_refuses_a_shell_command(tmp_path: Path) -> None:
    """systemd does not run ExecStart through a shell.

    A pipe, `&&` or a redirect works under cron and silently does the wrong
    thing here — the operators become literal arguments.
    """
    import pytest

    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=yes"))
    backend._which = lambda name: f"/usr/bin/{name}"  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="shell"):
        backend.install(
            [SchedulerJob(name="x", schedule="0 6 * * *", command="lh metrics ingest | tee log")]
        )
    assert list(tmp_path.iterdir()) == []


def test_environment_path_is_quoted(tmp_path: Path) -> None:
    """systemd splits Environment= on whitespace into separate assignments.

    An unquoted PATH containing a space sets PATH to its first fragment and
    drops the rest with a warning nobody reads.
    """
    from lazy_harness.scheduler import systemd as systemd_mod
    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = SystemdBackend(unit_dir=tmp_path, runner=_runner(lambda a: "Linger=yes"))
    backend._which = lambda name: f"/usr/bin/{name}"  # type: ignore[method-assign]

    original = systemd_mod.resolved_path
    systemd_mod.resolved_path = lambda: "/opt/My Tools/bin:/usr/bin"  # type: ignore[assignment]
    try:
        text = backend._service_text(SchedulerJob(name="x", schedule="0 6 * * *", command="lh x"))
    finally:
        systemd_mod.resolved_path = original  # type: ignore[assignment]

    assert 'Environment="PATH=/opt/My Tools/bin:/usr/bin"' in text


def test_install_reports_a_failed_systemctl_instead_of_a_green_tick(tmp_path: Path) -> None:
    """`install` appended every label before the runner ran and never looked
    at the result, so a rejected unit still printed a green tick — the
    'reports success while installing nothing' failure ADR-013 says was fixed."""
    import subprocess

    import pytest

    from lazy_harness.scheduler.systemd import SystemdBackend

    def failing(argv: list[str]) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ["systemctl", "--user", "enable"]:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Unit is invalid.")
        return subprocess.CompletedProcess(argv, 0, stdout="Linger=yes", stderr="")

    backend = SystemdBackend(unit_dir=tmp_path, runner=failing)
    backend._which = lambda name: f"/usr/bin/{name}"  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="Unit is invalid"):
        backend.install([SchedulerJob(name="x", schedule="0 6 * * *", command="lh x")])


def test_exec_start_resolves_against_the_scheduled_path_not_the_invoking_one(
    tmp_path: Path, monkeypatch
) -> None:
    """The binary is resolved with the same PATH the unit is given.

    `shutil.which` defaults to the invoking process's PATH, which is not what
    lands in `Environment=`. Both dirs below hold a binary of the same name,
    so only the resolver's choice of PATH can decide which one reaches
    `ExecStart` — and the wrong one is immune to every later filter, because
    an absolute ExecStart never consults PATH again.
    """
    from lazy_harness.scheduler import systemd as systemd_mod
    from lazy_harness.scheduler.systemd import SystemdBackend

    # A name that cannot exist on any host: the answer must come from the
    # constructed PATH, never from the machine running the test.
    binary = "lh-path-fixture"
    from_environment = tmp_path / "shell" / "bin"
    from_resolver = tmp_path / "unit" / "bin"
    for directory in (from_environment, from_resolver):
        directory.mkdir(parents=True)
        exe = directory / binary
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)

    monkeypatch.setenv("PATH", str(from_environment))
    monkeypatch.setattr(systemd_mod, "resolved_path", lambda: str(from_resolver))

    backend = SystemdBackend(unit_dir=tmp_path / "units", runner=_runner(lambda a: "Linger=yes"))
    text = backend._service_text(SchedulerJob(name="x", schedule="0 6 * * *", command=binary))

    assert f"ExecStart={from_resolver / binary}\n" in text
    assert str(from_environment) not in text
