"""Tests for cron expression parsing and per-backend rendering."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("30 3 * * 0", ("30", "3", "*", "*", "0")),
        ("0 */6 * * *", ("0", "*/6", "*", "*", "*")),
        ("*/30 * * * *", ("*/30", "*", "*", "*", "*")),
        ("15 2 1 * *", ("15", "2", "1", "*", "*")),
        ("0 9 * * 1-5", ("0", "9", "*", "*", "1-5")),
        ("  0   10   *   *   *  ", ("0", "10", "*", "*", "*")),
    ],
)
def test_parse_cron_keeps_every_field(expr: str, expected: tuple[str, ...]) -> None:
    from lazy_harness.scheduler.schedule import parse_cron

    s = parse_cron(expr)
    assert (s.minute, s.hour, s.day_of_month, s.month, s.day_of_week) == expected


@pytest.mark.parametrize("expr", ["", "0 9", "0 9 * *", "not a cron expression at all here"])
def test_parse_cron_rejects_malformed_expressions(expr: str) -> None:
    from lazy_harness.scheduler.schedule import ScheduleTranslationError, parse_cron

    with pytest.raises(ScheduleTranslationError, match="five fields"):
        parse_cron(expr)
