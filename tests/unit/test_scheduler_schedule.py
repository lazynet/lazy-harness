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


def test_render_launchd_hourly_on_the_hour_still_works() -> None:
    """`0 * * * *` worked before this branch and must keep working.

    launchd expresses it by omitting Hour: a StartCalendarInterval key that
    is absent means "every".
    """
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    assert render_launchd(parse_cron("0 * * * *")) == {"StartCalendarInterval": {"Minute": 0}}


def test_render_launchd_omits_star_fields() -> None:
    """A `*` field means "every", which launchd spells as an absent key."""
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    out = render_launchd(parse_cron("0 10 * * *"))
    assert out == {"StartCalendarInterval": {"Hour": 10, "Minute": 0}}
    assert "Day" not in out["StartCalendarInterval"]
    assert "Weekday" not in out["StartCalendarInterval"]


def test_render_launchd_minute_step_is_wall_clock_not_an_interval() -> None:
    """StartInterval is anchored to load time, not the wall clock.

    cron `*/30` means minute 0 and 30 of every hour; StartInterval=1800 means
    every 1800s from whenever launchd loaded the job. Emitting the calendar
    list keeps the declared meaning.
    """
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    assert render_launchd(parse_cron("*/30 * * * *")) == {
        "StartCalendarInterval": [{"Minute": 0}, {"Minute": 30}]
    }
    assert render_launchd(parse_cron("*/15 * * * *")) == {
        "StartCalendarInterval": [{"Minute": 0}, {"Minute": 15}, {"Minute": 30}, {"Minute": 45}]
    }


def test_render_launchd_refuses_a_minute_step_that_does_not_divide_the_hour() -> None:
    """cron `*/45` fires at :00 and :45 — gaps of 45 then 15 minutes.

    No uniform launchd interval reproduces that, so refuse rather than
    install a schedule that drifts from the declaration.
    """
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_launchd,
    )

    with pytest.raises(ScheduleTranslationError, match=r"\*/45"):
        render_launchd(parse_cron("*/45 * * * *"))


def test_render_launchd_refuses_day_of_month_and_day_of_week_together() -> None:
    """cron ORs the two day fields; launchd ANDs them.

    `0 9 1 * 1` fires on the 1st OR every Monday in cron — roughly five times
    a month — and only on a Monday falling on the 1st in launchd, roughly
    once a year.
    """
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_launchd,
    )

    with pytest.raises(ScheduleTranslationError, match="day_of_month"):
        render_launchd(parse_cron("0 9 1 * 1"))


@pytest.mark.parametrize(
    ("expr", "needle"),
    [
        ("0 25 * * *", "hour"),
        ("60 9 * * *", "minute"),
        ("0 9 32 * *", "day_of_month"),
        ("0 9 * * 8", "day_of_week"),
    ],
)
def test_render_launchd_rejects_out_of_range_fields(expr: str, needle: str) -> None:
    """launchd ignores or rejects an out-of-range key, so the job never fires
    while `lh status cron` reports it confidently."""
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_launchd,
    )

    with pytest.raises(ScheduleTranslationError, match=needle):
        render_launchd(parse_cron(expr))
