"""Cron expression parsing and per-backend rendering.

`config.toml` declares schedules in cron syntax (ADR-013) and each backend
renders that into its native form. A backend that cannot express an
expression faithfully raises rather than approximating it.

The previous launchd implementation approximated. `_cron_to_calendar`
recognised only the strict daily form `M H * * *`; everything else fell
through to a 3600-second default, so `0 */6 * * *` installed as hourly and a
weekly job ran 168 times a week. Nothing noticed, because `lh status cron`
and `lh selftest` both report on whether the label is loaded, never on
whether the installed schedule matches the declared one.
"""

from __future__ import annotations

from dataclasses import dataclass


class ScheduleTranslationError(Exception):
    """The expression is valid cron but this backend cannot express it."""


@dataclass(frozen=True, slots=True)
class Schedule:
    """A cron expression split into its five fields, unmodified."""

    minute: str
    hour: str
    day_of_month: str
    month: str
    day_of_week: str


def parse_cron(expr: str) -> Schedule:
    """Split a five-field cron expression. Raises on anything else."""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ScheduleTranslationError(
            f"cron expression must have five fields, got {len(parts)}: {expr!r}"
        )
    return Schedule(*parts)


def _as_int(field: str, name: str) -> int:
    if not field.isdigit():
        raise ScheduleTranslationError(f"launchd cannot express {name}={field!r}")
    return int(field)


def _step(field: str) -> int | None:
    """The N in `*/N`, or None if the field is not a step. Raises on `*/0`."""
    if not field.startswith("*/"):
        return None
    rest = field[2:]
    if not rest.isdigit() or int(rest) == 0:
        raise ScheduleTranslationError(f"malformed step field {field!r}")
    return int(rest)


def render_launchd(s: Schedule) -> dict[str, object]:
    """Render into a launchd StartCalendarInterval or StartInterval.

    launchd has no range or list syntax, so any field using `-` or `,`
    raises. So does a month restriction: the old translator ignored the
    month field entirely, which silently widened a yearly job into a
    monthly one.
    """
    fields = (
        ("minute", s.minute),
        ("hour", s.hour),
        ("day_of_month", s.day_of_month),
        ("month", s.month),
        ("day_of_week", s.day_of_week),
    )
    for name, field in fields:
        if "-" in field or "," in field:
            raise ScheduleTranslationError(
                f"launchd cannot express {name}={field!r}; declare separate jobs instead"
            )
    if s.month != "*":
        raise ScheduleTranslationError(
            f"launchd cannot express month={s.month!r}; declare separate jobs instead"
        )

    minute_step = _step(s.minute)
    if minute_step is not None:
        if (s.hour, s.day_of_month, s.day_of_week) != ("*", "*", "*"):
            raise ScheduleTranslationError(
                f"launchd cannot combine minute={s.minute!r} with hour={s.hour!r}, "
                f"day_of_month={s.day_of_month!r}, day_of_week={s.day_of_week!r}"
            )
        return {"StartInterval": minute_step * 60}

    minute = _as_int(s.minute, "minute")

    hour_step = _step(s.hour)
    if hour_step is not None:
        if (s.day_of_month, s.day_of_week) != ("*", "*"):
            raise ScheduleTranslationError(
                f"launchd cannot combine hour={s.hour!r} with "
                f"day_of_month={s.day_of_month!r}, day_of_week={s.day_of_week!r}"
            )
        return {
            "StartCalendarInterval": [
                {"Hour": h, "Minute": minute} for h in range(0, 24, hour_step)
            ]
        }

    entry: dict[str, int] = {"Hour": _as_int(s.hour, "hour"), "Minute": minute}
    if s.day_of_week != "*":
        entry["Weekday"] = _as_int(s.day_of_week, "day_of_week")
    if s.day_of_month != "*":
        entry["Day"] = _as_int(s.day_of_month, "day_of_month")
    return {"StartCalendarInterval": entry}
