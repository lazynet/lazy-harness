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


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("0 10 * * *", "*-*-* 10:00:00"),
        ("0 * * * *", "*-*-* *:00:00"),
        ("30 3 * * 0", "Sun *-*-* 03:30:00"),
        ("0 */6 * * *", "*-*-* 0/6:00:00"),
        ("*/30 * * * *", "*-*-* *:0/30:00"),
        ("15 2 1 * *", "*-*-01 02:15:00"),
        ("0 9 1 6 *", "*-06-01 09:00:00"),
    ],
)
def test_render_systemd_oncalendar(expr: str, expected: str) -> None:
    from lazy_harness.scheduler.schedule import parse_cron, render_systemd

    assert render_systemd(parse_cron(expr)) == expected


def test_render_systemd_expresses_a_weekday_range_launchd_refuses() -> None:
    """The asymmetry is the point of per-backend renderers.

    launchd has no range syntax and raises on this; systemd spells it
    natively, so refusing it here would be a translation loss with no cause.
    """
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd, render_systemd

    schedule = parse_cron("0 9 * * 1-5")
    assert render_systemd(schedule) == "Mon..Fri *-*-* 09:00:00"

    import pytest as _pytest

    from lazy_harness.scheduler.schedule import ScheduleTranslationError

    with _pytest.raises(ScheduleTranslationError):
        render_launchd(schedule)


def test_render_systemd_expresses_a_day_list() -> None:
    from lazy_harness.scheduler.schedule import parse_cron, render_systemd

    assert render_systemd(parse_cron("0 9 1,15 * *")) == "*-*-01,15 09:00:00"


def test_render_systemd_rejects_out_of_range_fields() -> None:
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_systemd,
    )

    with pytest.raises(ScheduleTranslationError, match="hour"):
        render_systemd(parse_cron("0 25 * * *"))


def test_render_cron_is_the_expression_itself() -> None:
    """Cron is lossless by construction: the declaration is the native form."""
    from lazy_harness.scheduler.schedule import parse_cron, render_cron

    for expr in ("0 9 * * 1-5", "*/45 * * * *", "15 2 1 6 *"):
        assert render_cron(parse_cron(expr)) == expr


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("0 9-17 * * *", "*-*-* 09..17:00:00"),
        ("0 9 1-15 * *", "*-*-01..15 09:00:00"),
        ("0 9 * 6-8 *", "*-06..08-* 09:00:00"),
    ],
)
def test_render_systemd_uses_the_double_dot_range_separator(expr: str, expected: str) -> None:
    """systemd's range separator is `..`, not `-`.

    Emitting `9-17` produces `OnCalendar=*-*-* 9-17:00:00`, which systemd
    rejects at load — the unit never fires and nothing reports why.
    """
    from lazy_harness.scheduler.schedule import parse_cron, render_systemd

    assert render_systemd(parse_cron(expr)) == expected


@pytest.mark.parametrize("expr", ["0 9 * * */2", "0 9 * * 1-3,5"])
def test_render_systemd_raises_rather_than_crashing_on_a_complex_dow(expr: str) -> None:
    """A bare ValueError escapes both install's guard and the CLI handler.

    `int("*/2")` and `int("3,5")` are not ScheduleTranslationError, so
    `lh scheduler install` died with a traceback instead of the handled
    "Nothing was installed" path.
    """
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_systemd,
    )

    with pytest.raises(ScheduleTranslationError):
        render_systemd(parse_cron(expr))


def test_render_systemd_refuses_day_of_month_and_day_of_week_together() -> None:
    """cron ORs the two day fields; systemd ANDs them, exactly like launchd.

    render_launchd already refuses this with that reasoning spelled out. Doing
    it in one renderer and not the other turns a declared ~5x/month job into
    a ~1x/year job with nothing reporting the difference.
    """
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_systemd,
    )

    with pytest.raises(ScheduleTranslationError, match="day_of_month"):
        render_systemd(parse_cron("0 9 1 * 1"))


def test_render_systemd_step_starts_at_the_field_lower_bound() -> None:
    """Day-of-month and month start at 1, not 0.

    `*-*-0/2` is rejected by systemd because day 0 does not exist.
    """
    from lazy_harness.scheduler.schedule import parse_cron, render_systemd

    assert render_systemd(parse_cron("0 9 */2 * *")) == "*-*-01/2 09:00:00"
    assert render_systemd(parse_cron("0 9 * */3 *")) == "*-01/3-* 09:00:00"
    # Hour and minute do start at 0.
    assert render_systemd(parse_cron("0 */6 * * *")) == "*-*-* 0/6:00:00"


def test_render_systemd_appends_the_timezone_when_one_is_given() -> None:
    """Without it, `OnCalendar=` is read in the machine's local zone.

    The agent station runs `Etc/UTC`, so a job declared for 08:00 fired at
    05:00 local — on time by the unit's own reckoning, three hours early by
    every other measure, and nothing reports a discrepancy.
    """
    from lazy_harness.scheduler.schedule import parse_cron, render_systemd

    assert (
        render_systemd(parse_cron("0 8 * * 1-5"), timezone="America/Argentina/Buenos_Aires")
        == "Mon..Fri *-*-* 08:00:00 America/Argentina/Buenos_Aires"
    )


def test_render_systemd_omits_the_timezone_when_none_is_given() -> None:
    """The zoneless form stays byte-identical, or every installed unit drifts."""
    from lazy_harness.scheduler.schedule import parse_cron, render_systemd

    assert render_systemd(parse_cron("0 8 * * 1-5")) == "Mon..Fri *-*-* 08:00:00"
    assert render_systemd(parse_cron("0 8 * * 1-5"), timezone=None) == "Mon..Fri *-*-* 08:00:00"
