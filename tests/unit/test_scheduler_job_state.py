"""Tests for JobState and backend-owned job discovery."""

from __future__ import annotations

from pathlib import Path


def test_job_state_has_an_unknown_member() -> None:
    """A backend that cannot introspect needs a way to say so.

    Spelling it as NOT_LOADED is what made every scheduled job render as a
    failure on any platform without launchctl.
    """
    from lazy_harness.scheduler.base import JobState

    assert {s.value for s in JobState} == {"loaded", "not_loaded", "unknown"}


def test_launchd_discover_returns_nothing_when_the_dir_is_absent(tmp_path: Path) -> None:
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend(agents_dir=tmp_path / "absent", runner=lambda argv: None)
    assert backend.discover() == []


def test_launchd_discover_reports_each_managed_job(tmp_path: Path) -> None:
    import subprocess

    from lazy_harness.scheduler.base import JobState, SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    def loaded(argv: list[str]):
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    backend = LaunchdBackend(agents_dir=tmp_path, runner=loaded)
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 */6 * * *", command="qmd sync")])

    records = backend.discover()
    assert len(records) == 1
    rec = records[0]
    assert rec.name == "qmd-sync"
    assert rec.label == "com.lazy-harness.qmd-sync"
    assert rec.schedule == "4x/day 00:00"
    assert rec.state is JobState.LOADED


def test_launchd_discover_reports_unknown_when_launchctl_is_absent(tmp_path: Path) -> None:
    """A missing launchctl is 'cannot check', not 'not loaded'."""
    from lazy_harness.scheduler.base import JobState, SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    def missing(argv: list[str]):
        raise FileNotFoundError(argv[0])

    backend = LaunchdBackend(agents_dir=tmp_path, runner=lambda argv: None)
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 6 * * *", command="qmd sync")])

    backend = LaunchdBackend(agents_dir=tmp_path, runner=missing)
    rec = backend.discover()[0]
    assert rec.state is JobState.UNKNOWN
    assert "launchctl" in rec.detail


def test_launchd_discover_reports_not_loaded_on_a_nonzero_exit(tmp_path: Path) -> None:
    import subprocess

    from lazy_harness.scheduler.base import JobState, SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    def absent(argv: list[str]):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Could not find service")

    backend = LaunchdBackend(agents_dir=tmp_path, runner=lambda argv: None)
    backend.install([SchedulerJob(name="qmd-sync", schedule="0 6 * * *", command="qmd sync")])

    backend = LaunchdBackend(agents_dir=tmp_path, runner=absent)
    assert backend.discover()[0].state is JobState.NOT_LOADED


def test_stub_backends_discover_nothing_without_raising() -> None:
    """systemd and cron have no discovery yet; they must degrade, not crash."""
    from lazy_harness.scheduler.cron import CronBackend
    from lazy_harness.scheduler.systemd import SystemdBackend

    assert SystemdBackend().discover() == []
    assert CronBackend().discover() == []


def test_default_runner_returns_the_completed_process() -> None:
    """job_state reads the exit status, so the runner must return it.

    The default runner called subprocess.run without returning, so every job
    reported UNKNOWN — the mechanism built to stop reporting a non-answer
    reported a non-answer for everything.
    """
    import sys

    from lazy_harness.scheduler.launchd import _default_runner

    # sys.executable rather than a PATH lookup: the point is that the runner
    # returns what it ran, and a missing helper binary would fail for an
    # unrelated reason.
    proc = _default_runner([sys.executable, "-c", "pass"])
    assert proc is not None
    assert proc.returncode == 0


def test_job_state_is_loaded_through_the_default_runner(tmp_path: Path) -> None:
    """Paired end-to-end check: with nothing injected, a real launchctl gives
    a real answer rather than UNKNOWN.

    Guarded on the binary rather than the platform: CI runs on ubuntu, where
    `launchctl` is absent and UNKNOWN is the correct result, so an unguarded
    assertion here passes on macOS and breaks the build.
    """
    import shutil

    import pytest

    from lazy_harness.scheduler.base import JobState
    from lazy_harness.scheduler.launchd import LaunchdBackend

    if shutil.which("launchctl") is None:
        pytest.skip("launchctl is absent; UNKNOWN is the correct answer here")

    backend = LaunchdBackend(agents_dir=tmp_path)
    state, detail = backend.job_state("com.lazy-harness.definitely-not-loaded")
    assert state is not JobState.UNKNOWN, detail


def test_launchd_backend_satisfies_the_protocol() -> None:
    """`label_for` was declared on the Protocol but only existed as `_label`,
    so isinstance was False on the one platform that installs anything."""
    from lazy_harness.scheduler.base import SchedulerBackend
    from lazy_harness.scheduler.cron import CronBackend
    from lazy_harness.scheduler.launchd import LaunchdBackend
    from lazy_harness.scheduler.systemd import SystemdBackend

    for backend in (LaunchdBackend(), SystemdBackend(), CronBackend()):
        assert isinstance(backend, SchedulerBackend), type(backend).__name__


def test_job_state_degrades_when_the_runner_raises_something_unexpected() -> None:
    """The runner is an injection point; `lh status cron` is read-only and
    must not propagate whatever it raises."""
    from lazy_harness.scheduler.base import JobState
    from lazy_harness.scheduler.launchd import LaunchdBackend

    def weird(_argv):
        raise RuntimeError("something nobody anticipated")

    state, detail = LaunchdBackend(runner=weird).job_state("com.lazy-harness.x")
    assert state is JobState.UNKNOWN
    assert "RuntimeError" in detail
