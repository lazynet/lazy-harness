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
