"""Tests for scheduler backends."""

from __future__ import annotations

from pathlib import Path


def test_scheduler_job_dataclass() -> None:
    from lazy_harness.scheduler.base import SchedulerJob

    job = SchedulerJob(name="qmd-sync", schedule="*/30 * * * *", command="lh knowledge sync")
    assert job.name == "qmd-sync"
    assert job.schedule == "*/30 * * * *"


def test_launchd_generate_plist(tmp_path: Path) -> None:
    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend(label_prefix="com.lazy-harness")
    job = SchedulerJob(name="qmd-sync", schedule="*/30 * * * *", command="lh knowledge sync")
    plist_path = backend.generate_plist(job, tmp_path)
    assert plist_path.is_file()
    assert plist_path.name == "com.lazy-harness.qmd-sync.plist"
    content = plist_path.read_text()
    assert "com.lazy-harness.qmd-sync" in content


def test_launchd_plist_uses_calendar_for_daily_schedule(tmp_path: Path) -> None:
    import plistlib

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend(label_prefix="com.lazy-harness")
    job = SchedulerJob(name="daily-embed", schedule="0 6 * * *", command="lh knowledge embed")
    plist_path = backend.generate_plist(job, tmp_path)
    with open(plist_path, "rb") as f:
        data = plistlib.load(f)

    assert "StartCalendarInterval" in data
    assert data["StartCalendarInterval"] == {"Hour": 6, "Minute": 0}
    assert "StartInterval" not in data


def test_launchd_plist_uses_interval_for_recurring_schedule(tmp_path: Path) -> None:
    import plistlib

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend(label_prefix="com.lazy-harness")
    job = SchedulerJob(name="sync", schedule="*/30 * * * *", command="lh knowledge sync")
    plist_path = backend.generate_plist(job, tmp_path)
    with open(plist_path, "rb") as f:
        data = plistlib.load(f)

    assert data["StartInterval"] == 1800
    assert "StartCalendarInterval" not in data


def test_launchd_plist_includes_stdout_and_stderr_paths(tmp_path: Path) -> None:
    import plistlib

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend(label_prefix="com.lazy-harness")
    job = SchedulerJob(name="myjob", schedule="*/10 * * * *", command="echo hi")
    plist_path = backend.generate_plist(job, tmp_path)
    with open(plist_path, "rb") as f:
        data = plistlib.load(f)

    assert "StandardOutPath" in data
    assert "StandardErrorPath" in data
    assert data["StandardOutPath"].endswith("myjob-stdout.log")
    assert data["StandardErrorPath"].endswith("myjob-stderr.log")


def test_launchd_list_jobs(tmp_path: Path) -> None:
    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend(label_prefix="com.lazy-harness")
    job = SchedulerJob(name="test-job", schedule="*/10 * * * *", command="echo hi")
    backend.generate_plist(job, tmp_path)
    jobs = backend.list_jobs(tmp_path)
    assert len(jobs) == 1
    assert jobs[0] == "com.lazy-harness.test-job"


def test_generate_plist_honours_a_six_hourly_schedule(tmp_path: Path) -> None:
    """`0 */6 * * *` was installed as StartInterval=3600 — 6x over-execution."""
    import plistlib

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    job = SchedulerJob(name="qmd-sync", schedule="0 */6 * * *", command="qmd sync")
    path = LaunchdBackend().generate_plist(job, tmp_path)

    plist = plistlib.loads(path.read_bytes())
    assert "StartInterval" not in plist
    assert plist["StartCalendarInterval"] == [
        {"Hour": 0, "Minute": 0},
        {"Hour": 6, "Minute": 0},
        {"Hour": 12, "Minute": 0},
        {"Hour": 18, "Minute": 0},
    ]


def test_generate_plist_honours_a_weekly_schedule(tmp_path: Path) -> None:
    """`30 3 * * 0` was installed as StartInterval=3600 — 168x over-execution."""
    import plistlib

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    job = SchedulerJob(name="weekly-review", schedule="30 3 * * 0", command="lh knowledge review")
    path = LaunchdBackend().generate_plist(job, tmp_path)

    plist = plistlib.loads(path.read_bytes())
    assert "StartInterval" not in plist
    assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 30, "Weekday": 0}


def test_generate_plist_refuses_an_untranslatable_schedule(tmp_path: Path) -> None:
    """Refusing beats installing a different schedule than the one declared."""
    import pytest

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend
    from lazy_harness.scheduler.schedule import ScheduleTranslationError

    job = SchedulerJob(name="weekdays", schedule="0 9 * * 1-5", command="echo hi")
    with pytest.raises(ScheduleTranslationError, match="1-5"):
        LaunchdBackend().generate_plist(job, tmp_path)


def test_install_writes_nothing_for_an_untranslatable_schedule(tmp_path: Path) -> None:
    """The refusal must reach `install`, not be swallowed into a partial run."""
    import pytest

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend
    from lazy_harness.scheduler.schedule import ScheduleTranslationError

    backend = LaunchdBackend()
    job = SchedulerJob(name="weekdays", schedule="0 9 * * 1-5", command="echo hi")
    with pytest.raises(ScheduleTranslationError):
        backend.generate_plist(job, tmp_path)
    assert list(tmp_path.iterdir()) == []
