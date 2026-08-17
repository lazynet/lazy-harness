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


def test_install_validates_every_job_before_writing_any(tmp_path: Path) -> None:
    """One untranslatable job must not leave a half-installed set.

    install() used to write and load each job as it went, so a bad job in the
    middle left the earlier ones installed, the later ones untouched, and the
    caller with a traceback.
    """
    import pytest

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend
    from lazy_harness.scheduler.schedule import ScheduleTranslationError

    loaded: list[list[str]] = []

    backend = LaunchdBackend(agents_dir=tmp_path, runner=lambda argv: loaded.append(argv))
    jobs = [
        SchedulerJob(name="good-a", schedule="0 6 * * *", command="a"),
        SchedulerJob(name="bad", schedule="0 9 * * 1-5", command="b"),
        SchedulerJob(name="good-c", schedule="0 7 * * *", command="c"),
    ]

    with pytest.raises(ScheduleTranslationError, match="bad"):
        backend.install(jobs)

    assert list(tmp_path.iterdir()) == []
    assert loaded == []


def test_install_writes_every_job_when_all_translate(tmp_path: Path) -> None:
    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend(agents_dir=tmp_path, runner=lambda argv: None)
    jobs = [
        SchedulerJob(name="a", schedule="0 6 * * *", command="a"),
        SchedulerJob(name="b", schedule="0 7 * * *", command="b"),
    ]

    installed = backend.install(jobs)

    assert installed == ["com.lazy-harness.a", "com.lazy-harness.b"]
    assert {p.name for p in tmp_path.iterdir()} == {
        "com.lazy-harness.a.plist",
        "com.lazy-harness.b.plist",
    }


def test_launchd_backend_constructs_without_arguments() -> None:
    """Paired smoke test: always injecting agents_dir and runner would leave
    the default resolution completely untested."""
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend()
    assert backend._agents_dir.name == "LaunchAgents"
    assert backend._runner is not None

def test_launchd_plist_uses_wall_clock_entries_for_a_minute_step(tmp_path: Path) -> None:
    """Replaces the StartInterval assertion this branch made obsolete.

    StartInterval counts from load time, so `*/30` fired at load+30m rather
    than at :00 and :30. The calendar list keeps the declared meaning.
    """
    import plistlib

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    job = SchedulerJob(name="qmd-sync", schedule="*/30 * * * *", command="lh knowledge sync")
    path = LaunchdBackend().generate_plist(job, tmp_path)

    data = plistlib.loads(path.read_bytes())
    assert "StartInterval" not in data
    assert data["StartCalendarInterval"] == [{"Minute": 0}, {"Minute": 30}]


def _write_plist(path, payload: dict) -> None:
    import plistlib

    with open(path, "wb") as f:
        plistlib.dump({"Label": "com.lazy-harness.x", **payload}, f)


def test_format_schedule_reports_a_weekly_entry_as_weekly(tmp_path) -> None:
    """A dict carrying Weekday was reported as `daily`."""
    from lazy_harness.scheduler.launchd import format_schedule

    p = tmp_path / "x.plist"
    _write_plist(p, {"StartCalendarInterval": {"Hour": 3, "Minute": 30, "Weekday": 0}})
    assert format_schedule(p) == "weekly Sun 03:30"


def test_format_schedule_reports_a_monthly_entry_as_monthly(tmp_path) -> None:
    """A dict carrying Day was reported as `daily`."""
    from lazy_harness.scheduler.launchd import format_schedule

    p = tmp_path / "x.plist"
    _write_plist(p, {"StartCalendarInterval": {"Hour": 2, "Minute": 15, "Day": 1}})
    assert format_schedule(p) == "monthly day 1 02:15"


def test_format_schedule_reports_an_hour_list_as_times_per_day(tmp_path) -> None:
    """A 4-entry hour list was reported as `4x/week`. It is 4x/day."""
    from lazy_harness.scheduler.launchd import format_schedule

    p = tmp_path / "x.plist"
    _write_plist(
        p,
        {
            "StartCalendarInterval": [
                {"Minute": 0, "Hour": h} for h in (0, 6, 12, 18)
            ]
        },
    )
    assert format_schedule(p) == "4x/day 00:00"


def test_format_schedule_reports_a_minute_list_as_times_per_hour(tmp_path) -> None:
    from lazy_harness.scheduler.launchd import format_schedule

    p = tmp_path / "x.plist"
    _write_plist(p, {"StartCalendarInterval": [{"Minute": 0}, {"Minute": 30}]})
    assert format_schedule(p) == "2x/hour :00"


def test_format_schedule_reports_an_hourly_entry_as_hourly(tmp_path) -> None:
    """`{"Minute": 0}` means every hour; it was reported as `daily 00:00`."""
    from lazy_harness.scheduler.launchd import format_schedule

    p = tmp_path / "x.plist"
    _write_plist(p, {"StartCalendarInterval": {"Minute": 0}})
    assert format_schedule(p) == "hourly :00"

