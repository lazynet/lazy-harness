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


def test_render_launchd_weekly_is_weekly_not_hourly() -> None:
    """Was installed as StartInterval=3600 — 168x over-execution."""
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    out = render_launchd(parse_cron("30 3 * * 0"))
    assert out == {"StartCalendarInterval": {"Hour": 3, "Minute": 30, "Weekday": 0}}


def test_render_launchd_every_six_hours_is_not_hourly() -> None:
    """ADR-013's own example. Was installed as StartInterval=3600 — 6x."""
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    out = render_launchd(parse_cron("0 */6 * * *"))
    assert out == {
        "StartCalendarInterval": [
            {"Hour": 0, "Minute": 0},
            {"Hour": 6, "Minute": 0},
            {"Hour": 12, "Minute": 0},
            {"Hour": 18, "Minute": 0},
        ]
    }


def test_render_launchd_monthly_is_monthly() -> None:
    """Was installed as StartInterval=3600 — roughly 720x."""
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    out = render_launchd(parse_cron("15 2 1 * *"))
    assert out == {"StartCalendarInterval": {"Hour": 2, "Minute": 15, "Day": 1}}


def test_render_launchd_daily_unchanged() -> None:
    """The one form the old translator got right. It must stay right."""
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    assert render_launchd(parse_cron("0 10 * * *")) == {
        "StartCalendarInterval": {"Hour": 10, "Minute": 0}
    }


def test_render_launchd_step_minutes_uses_interval() -> None:
    """The other form the old translator got right."""
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    assert render_launchd(parse_cron("*/30 * * * *")) == {"StartInterval": 1800}


def test_render_launchd_refuses_a_weekday_range() -> None:
    """launchd has no range syntax.

    Refusing is the point: the old code turned this into hourly, which also
    fired on weekends.
    """
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_launchd,
    )

    with pytest.raises(ScheduleTranslationError, match="1-5"):
        render_launchd(parse_cron("0 9 * * 1-5"))


def test_render_launchd_refuses_a_list() -> None:
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_launchd,
    )

    with pytest.raises(ScheduleTranslationError, match="1,15"):
        render_launchd(parse_cron("0 9 1,15 * *"))


def test_render_launchd_refuses_a_month_restriction() -> None:
    """launchd's StartCalendarInterval has a Month key, but the old code
    ignored the field entirely. Refuse rather than silently widen."""
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_launchd,
    )

    with pytest.raises(ScheduleTranslationError, match="month"):
        render_launchd(parse_cron("0 9 1 6 *"))


def test_render_launchd_rejects_a_zero_step() -> None:
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_launchd,
    )

    with pytest.raises(ScheduleTranslationError, match=r"\*/0"):
        render_launchd(parse_cron("*/0 * * * *"))
