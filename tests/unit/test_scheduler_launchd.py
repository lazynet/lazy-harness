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


def test_launchd_list_jobs(tmp_path: Path) -> None:
    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend(label_prefix="com.lazy-harness")
    job = SchedulerJob(name="test-job", schedule="*/10 * * * *", command="echo hi")
    backend.generate_plist(job, tmp_path)
    jobs = backend.list_jobs(tmp_path)
    assert len(jobs) == 1
    assert jobs[0] == "com.lazy-harness.test-job"
