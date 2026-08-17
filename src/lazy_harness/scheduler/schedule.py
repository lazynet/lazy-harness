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


_SYSTEMD_DOW = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

# systemd's calendar fields, with the lower bound a `*/N` step starts from.
# Day-of-month and month begin at 1: rendering `*-*-0/2` names a day that does
# not exist and systemd rejects the unit.
_SYSTEMD_FIELDS = {"minute": 0, "hour": 0, "day_of_month": 1, "month": 1}


def _check_range(field: str, name: str) -> None:
    """Validate every literal number in a cron field against its range.

    systemd accepts ranges and lists where launchd does not, so the numbers
    have to be checked without collapsing the field to a single value. An
    out-of-range value makes systemd reject the unit at load, which surfaces
    as a job that silently never runs.
    """
    low, high = _RANGES[name]
    for part in field.replace("/", ",").replace("-", ",").split(","):
        if part in ("", "*"):
            continue
        if not part.isdigit():
            raise ScheduleTranslationError(f"systemd cannot express {name}={field!r}")
        if not low <= int(part) <= high:
            raise ScheduleTranslationError(
                f"{name}={field!r} is outside the valid range {low}-{high}"
            )


def _systemd_dow(field: str) -> str:
    """Render day-of-week as systemd day names, or '' for every day.

    Anything past a plain value or a simple range raises rather than reaching
    `int()`: a bare ValueError is not a ScheduleTranslationError, so it would
    escape both `install`'s guard and the CLI handler and surface as a
    traceback.
    """
    if field == "*":
        return ""

    def name(part: str) -> str:
        if not part.isdigit():
            raise ScheduleTranslationError(
                f"systemd cannot express day_of_week={field!r}; declare separate jobs instead"
            )
        return _SYSTEMD_DOW[int(part) % 7]

    if "-" in field:
        if field.count("-") != 1 or "," in field or "/" in field:
            raise ScheduleTranslationError(
                f"systemd cannot express day_of_week={field!r}; declare separate jobs instead"
            )
        start, end = field.split("-")
        return f"{name(start)}..{name(end)}"
    if "/" in field:
        raise ScheduleTranslationError(
            f"systemd cannot express day_of_week={field!r}; declare separate jobs instead"
        )
    return ",".join(name(p) for p in field.split(","))


def _systemd_num(field: str, fname: str) -> str:
    """Render a numeric field, keeping `*`, steps, ranges and lists intact.

    Ranges use `..`, which is systemd's separator — emitting cron's `-` yields
    a unit systemd refuses at load.
    """
    width = 2 if fname in ("day_of_month", "month", "hour", "minute") else 2
    low = _SYSTEMD_FIELDS[fname]

    def pad(value: str) -> str:
        return value.zfill(width) if value.isdigit() else value

    if field == "*":
        return "*"
    if field.startswith("*/"):
        step = field[2:]
        return f"{pad(str(low))}/{step}" if low else f"0/{step}"

    rendered: list[str] = []
    for part in field.split(","):
        if "-" in part:
            if part.count("-") != 1:
                raise ScheduleTranslationError(f"systemd cannot express {fname}={field!r}")
            start, end = part.split("-")
            rendered.append(f"{pad(start)}..{pad(end)}")
        else:
            rendered.append(pad(part))
    return ",".join(rendered)


def render_systemd(s: Schedule) -> str:
    """Render into a systemd `OnCalendar=` expression.

    systemd's calendar syntax covers ranges, lists and month restrictions, so
    this accepts expressions `render_launchd` refuses. That asymmetry is why
    each backend renders separately instead of sharing one lowest common
    denominator.
    """
    for name in ("minute", "hour", "day_of_month", "day_of_week"):
        _check_range(getattr(s, name), name)
    for part in s.month.replace("/", ",").replace("-", ",").split(","):
        if part in ("", "*"):
            continue
        if not part.isdigit() or not 1 <= int(part) <= 12:
            raise ScheduleTranslationError(
                f"month={s.month!r} is outside the valid range 1-12"
            )

    # cron ORs the two day fields when both are restricted; systemd ANDs them,
    # exactly as launchd does. `0 9 1 * 1` is roughly five times a month in
    # cron and roughly once a year here.
    if s.day_of_month != "*" and s.day_of_week != "*":
        raise ScheduleTranslationError(
            f"cron ORs day_of_month={s.day_of_month!r} with day_of_week={s.day_of_week!r} "
            "and systemd ANDs them; declare separate jobs instead"
        )

    dow = _systemd_dow(s.day_of_week)
    date = f"*-{_systemd_num(s.month, 'month')}-{_systemd_num(s.day_of_month, 'day_of_month')}"
    time_part = (
        f"{_systemd_num(s.hour, 'hour')}:{_systemd_num(s.minute, 'minute')}:00"
    )
    calendar = f"{date} {time_part}"
    return f"{dow} {calendar}" if dow else calendar


def render_cron(s: Schedule) -> str:
    """Render back to cron. Lossless: the declaration is already the native form."""
    return f"{s.minute} {s.hour} {s.day_of_month} {s.month} {s.day_of_week}"
