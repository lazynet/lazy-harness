"""Tests for `lh status` view helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


def test_format_tokens_thresholds() -> None:
    from lazy_harness.monitoring.views._helpers import format_tokens

    assert format_tokens(0) == "0"
    assert format_tokens(999) == "999"
    assert format_tokens(1_500) == "1.5K"
    assert format_tokens(2_500_000) == "2.5M"


def test_format_tokens_switches_to_billions() -> None:
    """Cross-profile totals run to ten figures; 10310.6M is unreadable."""
    from lazy_harness.monitoring.views._helpers import format_tokens

    assert format_tokens(999_999_999) == "1000.0M"
    assert format_tokens(1_500_000_000) == "1.5G"
    assert format_tokens(10_310_600_000) == "10.3G"


def test_format_size_returns_question_for_missing(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views._helpers import format_size

    assert format_size(tmp_path / "missing") == "?"


def test_format_size_units(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views._helpers import format_size

    small = tmp_path / "small.txt"
    small.write_text("x" * 50)
    assert format_size(small) == "50B"

    medium = tmp_path / "medium.txt"
    medium.write_text("x" * 2048)
    assert format_size(medium) == "2K"

    big = tmp_path / "big.txt"
    big.write_text("x" * (1_500_000))
    assert format_size(big) == "1.4M"


def test_time_ago_just_now() -> None:
    from lazy_harness.monitoring.views._helpers import time_ago

    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    assert time_ago(ts) == "just now"


def test_time_ago_minutes_hours_days() -> None:
    from lazy_harness.monitoring.views._helpers import time_ago

    now = datetime.now()
    assert time_ago((now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S")) == "5m ago"
    assert time_ago((now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")) == "3h ago"
    assert time_ago((now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")) == "2d ago"


def test_time_ago_handles_tz_offset() -> None:
    from lazy_harness.monitoring.views._helpers import time_ago

    now = datetime.now()
    ts = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S") + "-03:00"
    assert time_ago(ts) == "10m ago"


def test_time_ago_invalid_input() -> None:
    from lazy_harness.monitoring.views._helpers import time_ago

    assert time_ago("") == "—"
    assert time_ago("not a date") == "?"


def test_decode_project_name_root() -> None:
    from lazy_harness.monitoring.views._helpers import decode_project_name

    assert decode_project_name("-") == "(root)"
    assert decode_project_name("foo") == "foo"


def test_decode_project_name_known_container_fallback() -> None:
    from lazy_harness.monitoring.views._helpers import decode_project_name

    # Path doesn't exist on disk → fallback to known-container heuristic
    assert decode_project_name("-Users-x-repos-lazy-claudecode") == "lazy-claudecode"


def test_last_hook_line_returns_most_recent(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views._helpers import last_hook_line

    log = tmp_path / "hooks.log"
    log.write_text(
        "2026-04-01T10:00:00 session-export: fired cwd=/foo\n"
        "2026-04-01T10:01:00 session-export: fired cwd=/bar\n"
        "2026-04-01T10:02:00 compound-loop: fired cwd=/bar\n"
    )
    line = last_hook_line(log, "session-export")
    assert "fired" in line
    assert "/bar" in line
    assert "10:01:00" in line


def test_last_hook_line_missing_log(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views._helpers import last_hook_line

    assert last_hook_line(tmp_path / "nope.log", "x") == ""


def test_last_log_timestamp_finds_bracket(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views._helpers import last_log_timestamp

    log = tmp_path / "x.log"
    log.write_text("[2026-04-01 10:00:00] starting\n[2026-04-01 10:05:30] sync OK\n")
    ts = last_log_timestamp(log)
    assert "2026-04-01T10:05:30" == ts


def test_count_errors_today(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views._helpers import count_errors_today

    today = datetime.now().strftime("%Y-%m-%d")
    log = tmp_path / "x.log"
    log.write_text(
        f"{today}T10:00:00 session-export: fired\n"
        f"{today}T10:01:00 session-export: parse error\n"
        f"{today}T10:02:00 compound-loop: failed to spawn\n"
        "2025-01-01T00:00:00 unrelated parse error\n"
    )
    assert count_errors_today(log) == 2


def test_count_errors_today_missing_log(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views._helpers import count_errors_today

    assert count_errors_today(tmp_path / "nope.log") == 0


def test_launchctl_loaded_is_gone() -> None:
    """It returned False for 'cannot check'. Nothing may reintroduce that shape."""
    from lazy_harness.monitoring.views import _helpers

    assert not hasattr(_helpers, "launchctl_loaded")


def test_status_context_exposes_the_backend_not_a_launchd_prefix() -> None:
    """Reverse-DNS labelling is a launchd convention; the status layer must
    not know it, and must not glob a macOS-only directory."""
    from lazy_harness.core.config import Config
    from lazy_harness.monitoring.views._helpers import StatusContext

    ctx = StatusContext.build(Config())
    assert not hasattr(ctx, "launchd_prefix")
    assert ctx.scheduler_backend is not None






def test_lock_state_never_acquires_the_lock(tmp_path: Path) -> None:
    """The probe must be read-only.

    Acquiring the worker's own exclusive flock to test it makes the probe
    win the race: measured at 16.6% denial under contention, and every
    denial is the compound-loop worker logging "another worker is running",
    exiting 0, and leaving the queue undrained until the next scheduled run.
    """
    import fcntl

    from lazy_harness.monitoring.views._helpers import lock_state

    lock = tmp_path / ".worker.lock"
    lock.touch()

    for _ in range(200):
        lock_state(lock)

    # If the probe ever took the lock and failed to release it, or is holding
    # it now, this acquire fails.
    fd = open(lock, "a")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        fd.close()


def test_lock_state_reports_unknown_when_it_cannot_check(tmp_path: Path, monkeypatch) -> None:
    """A missing `lsof` is 'cannot check', not 'not locked'.

    Reading absence as free is the dangerous direction: the view then claims
    the worker is idle while it runs. Same three-valued reasoning as JobState.
    """
    import subprocess

    from lazy_harness.monitoring.views._helpers import LockState, lock_state

    lock = tmp_path / ".worker.lock"
    lock.touch()

    def missing(*_a, **_k):
        raise FileNotFoundError("lsof")

    monkeypatch.setattr(subprocess, "run", missing)
    state, detail = lock_state(lock)
    assert state is LockState.UNKNOWN
    assert "lsof" in detail


def test_lock_state_reports_free_for_a_missing_file(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views._helpers import LockState, lock_state

    state, _ = lock_state(tmp_path / "absent.lock")
    assert state is LockState.FREE


def test_lock_state_reports_held_when_the_lock_is_taken(tmp_path: Path) -> None:
    import fcntl
    import shutil

    import pytest

    from lazy_harness.monitoring.views._helpers import LockState, lock_state

    if shutil.which("lsof") is None:
        pytest.skip("lsof is not installed; the probe correctly reports UNKNOWN")

    lock = tmp_path / ".worker.lock"
    lock.touch()
    fd = open(lock, "a")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        state, _ = lock_state(lock)
        assert state is LockState.HELD
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
