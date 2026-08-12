"""Period resolution and dimensional aggregation for token/cost reporting.

Deliberately free of Rich so the table renderer and the JSON emitter can be fed
from one `Aggregation` instead of two aggregation paths that drift apart.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

DIMENSIONS = ("profile", "project", "model", "day", "week", "month")

_N_DAYS = re.compile(r"^(\d+)d$")


@dataclass(frozen=True)
class Period:
    """A resolved `--period` spec, in the shape `MetricsDB.query_stats` wants."""

    spec: str
    period: str
    since: str | None
    label: str


def resolve_period(spec: str, *, now: datetime | None = None) -> Period:
    """Translate a `--period` string into a DB filter plus a human label."""
    today = now or datetime.now()

    if spec == "today":
        stamp = today.strftime("%Y-%m-%d")
        return Period(spec=spec, period=stamp, since=None, label="Today")
    if spec == "all":
        return Period(spec=spec, period="all", since=None, label="All time")
    if spec == "month":
        return Period(
            spec=spec,
            period=today.strftime("%Y-%m"),
            since=None,
            label=today.strftime("%B %Y"),
        )
    if spec == "week":
        return _since_days(spec, today, 7, "Last 7 days")

    match = _N_DAYS.match(spec)
    if match:
        days = int(match.group(1))
        return _since_days(spec, today, days, f"Last {days} days")

    return Period(spec=spec, period=spec, since=None, label=spec)


def _since_days(spec: str, today: datetime, days: int, label: str) -> Period:
    since = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    return Period(spec=spec, period="all", since=since, label=label)


@dataclass
class Bucket:
    """Accumulated token counts and cost for one group of rows."""

    key: dict[str, str] = field(default_factory=dict)
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_create: int = 0
    cost: float = 0.0
    sessions: set[str] = field(default_factory=set)

    def add(self, row: dict[str, Any]) -> None:
        self.input += int(row.get("input", 0) or 0)
        self.output += int(row.get("output", 0) or 0)
        self.cache_read += int(row.get("cache_read", 0) or 0)
        self.cache_create += int(row.get("cache_create", 0) or 0)
        self.cost += float(row.get("cost", 0.0) or 0.0)
        session = str(row.get("session") or "")
        if session:
            self.sessions.add(session)

    @property
    def total_input(self) -> int:
        """Input as the table has always reported it: prompt plus both caches."""
        return self.input + self.cache_read + self.cache_create

    @property
    def cache_pct(self) -> int:
        total = self.total_input
        return int(self.cache_read * 100 / total) if total > 0 else 0

    @property
    def session_count(self) -> int:
        return len(self.sessions)


@dataclass
class Aggregation:
    dimensions: list[str]
    filters: dict[str, str]
    groups: list[Bucket]
    subtotals: list[Bucket]
    total: Bucket


def _dimension_value(row: dict[str, Any], dimension: str) -> str:
    if dimension in ("profile", "project", "model"):
        return str(row.get(dimension) or "") or "unknown"

    date = str(row.get("date") or "")
    if not date:
        return "unknown"
    if dimension == "day":
        return date
    if dimension == "month":
        return date[:7]
    # week
    try:
        parsed = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return "unknown"
    iso = parsed.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


FILTERABLE = ("profile", "project", "model")


def _matches(row: dict[str, Any], filters: dict[str, str]) -> bool:
    """Case-insensitive substring match on each supplied filter."""
    for name, needle in filters.items():
        if not needle:
            continue
        haystack = str(row.get(name) or "").lower()
        if needle.lower() not in haystack:
            return False
    return True


def aggregate(
    rows: list[dict[str, Any]],
    dimensions: list[str],
    filters: dict[str, str] | None = None,
) -> Aggregation:
    """Group `rows` by `dimensions`, in the order given."""
    unknown = [d for d in dimensions if d not in DIMENSIONS]
    if unknown:
        raise ValueError(
            f"unknown dimension(s): {', '.join(unknown)}; valid: {', '.join(DIMENSIONS)}"
        )

    active = {k: v for k, v in (filters or {}).items() if v}
    groups: dict[tuple[str, ...], Bucket] = {}
    subtotals: dict[str, Bucket] = {}
    total = Bucket()
    lead = dimensions[0] if len(dimensions) > 1 else None

    for row in rows:
        if not _matches(row, active):
            continue
        values = tuple(_dimension_value(row, d) for d in dimensions)
        bucket = groups.get(values)
        if bucket is None:
            bucket = Bucket(key=dict(zip(dimensions, values, strict=True)))
            groups[values] = bucket
        bucket.add(row)
        total.add(row)

        if lead is not None:
            sub = subtotals.get(values[0])
            if sub is None:
                sub = Bucket(key={lead: values[0]})
                subtotals[values[0]] = sub
            sub.add(row)

    return Aggregation(
        dimensions=list(dimensions),
        filters=dict(active),
        groups=[groups[k] for k in sorted(groups)],
        subtotals=[subtotals[k] for k in sorted(subtotals)],
        total=total,
    )
