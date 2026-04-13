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


def test_launchd_parse_interval_minutes() -> None:
    from lazy_harness.scheduler.launchd import _cron_to_interval

    assert _cron_to_interval("*/30 * * * *") == 1800
    assert _cron_to_interval("*/5 * * * *") == 300
    assert _cron_to_interval("0 * * * *") == 3600


def test_cron_to_calendar_daily() -> None:
    from lazy_harness.scheduler.launchd import _cron_to_calendar

    assert _cron_to_calendar("0 6 * * *") == {"Hour": 6, "Minute": 0}
    assert _cron_to_calendar("30 23 * * *") == {"Hour": 23, "Minute": 30}


def test_cron_to_calendar_returns_none_for_interval() -> None:
    from lazy_harness.scheduler.launchd import _cron_to_calendar

    assert _cron_to_calendar("*/30 * * * *") is None


def test_cron_to_calendar_returns_none_when_not_every_day() -> None:
    from lazy_harness.scheduler.launchd import _cron_to_calendar

    # Specific day-of-month or day-of-week not supported → fall through
    assert _cron_to_calendar("0 6 1 * *") is None
    assert _cron_to_calendar("0 6 * * 1") is None


def test_cron_to_calendar_malformed() -> None:
    from lazy_harness.scheduler.launchd import _cron_to_calendar

    assert _cron_to_calendar("nope") is None
    assert _cron_to_calendar("") is None


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
