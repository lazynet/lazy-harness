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
    log.write_text(
        "[2026-04-01 10:00:00] starting\n"
        "[2026-04-01 10:05:30] sync OK\n"
    )
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
