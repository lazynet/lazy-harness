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


# Inclusive bounds per cron field, used to reject values launchd would
# silently ignore — an out-of-range key means the job never fires while the
# status view still reports it confidently.
_RANGES: dict[str, tuple[int, int]] = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day_of_month": (1, 31),
    "day_of_week": (0, 7),
}

# launchd StartCalendarInterval key per cron field.
_PLIST_KEYS = {
    "minute": "Minute",
    "hour": "Hour",
    "day_of_month": "Day",
    "day_of_week": "Weekday",
}


def _as_int(field: str, name: str) -> int:
    if not field.isdigit():
        raise ScheduleTranslationError(f"launchd cannot express {name}={field!r}")
    value = int(field)
    low, high = _RANGES[name]
    if not low <= value <= high:
        raise ScheduleTranslationError(
            f"{name}={field!r} is outside the valid range {low}-{high}"
        )
    return value


def _step(field: str) -> int | None:
    """The N in `*/N`, or None if the field is not a step. Raises on `*/0`."""
    if not field.startswith("*/"):
        return None
    rest = field[2:]
    if not rest.isdigit() or int(rest) == 0:
        raise ScheduleTranslationError(f"malformed step field {field!r}")
    return int(rest)


def render_launchd(s: Schedule) -> dict[str, object]:
    """Render into a launchd StartCalendarInterval.

    A `*` field is expressed by omitting its key — that is what launchd reads
    as "every". Ranges, lists and month restrictions have no launchd form and
    raise, as does a step that does not divide its field evenly, because no
    uniform launchd schedule reproduces the uneven gaps cron would produce.

    `StartInterval` is never emitted. It counts from load time rather than the
    wall clock, so `*/30` would fire at load+30m instead of at :00 and :30 —
    an approximation, which is the class of defect this module exists to
    remove.
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
    # cron ORs the two day fields when both are restricted; launchd ANDs them.
    # `0 9 1 * 1` is roughly five times a month in cron and once a year here.
    if s.day_of_month != "*" and s.day_of_week != "*":
        raise ScheduleTranslationError(
            f"cron ORs day_of_month={s.day_of_month!r} with day_of_week={s.day_of_week!r} "
            "and launchd ANDs them; declare separate jobs instead"
        )

    # A step in one field expands into one calendar entry per value; a step in
    # more than one would be a cross product launchd cannot be trusted with.
    stepped = [(n, f, _step(f)) for n, f in fields if n != "month" and _step(f) is not None]
    if len(stepped) > 1:
        names = ", ".join(f"{n}={f!r}" for n, f, _ in stepped)
        raise ScheduleTranslationError(f"launchd cannot combine steps in {names}")

    base: dict[str, int] = {}
    for name, field in fields:
        if name == "month" or field == "*" or field.startswith("*/"):
            continue
        base[_PLIST_KEYS[name]] = _as_int(field, name)

    if not stepped:
        return {"StartCalendarInterval": base}

    name, field, step = stepped[0]
    low, high = _RANGES[name]
    span = high + 1 if name != "day_of_month" else high
    if span % step:
        raise ScheduleTranslationError(
            f"{name}={field!r} does not divide {span} evenly, so no launchd schedule "
            "reproduces the gaps cron would produce; declare separate jobs instead"
        )
    key = _PLIST_KEYS[name]
    start = low
    return {
        "StartCalendarInterval": [
            {**base, key: v} for v in range(start, high + 1, step)
        ]
    }
