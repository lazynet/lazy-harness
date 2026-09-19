"""`lh status sessions` view — daily breakdown of sessions, tokens, cost."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from rich.console import Group, RenderableType
from rich.table import Table

from lazy_harness.monitoring.aggregate import resolve_period
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.views._helpers import format_tokens


def _period_label(period: str) -> str:
    return resolve_period(period).label


def _query_for_period(db: MetricsDB, period: str) -> list[dict[str, Any]]:
    resolved = resolve_period(period)
    return db.query_stats(period=resolved.period, since=resolved.since)


def render(db: MetricsDB, period: str) -> RenderableType:
    header = (
        f"[bold]Period: {_period_label(period)}[/bold]\n"
        "Measures: Billed cost · API-equivalent cost\n"
    )
    rows = _query_for_period(db, period)
    if not rows:
        return Group(header, "[dim]No data. Run a session first.[/dim]")

    by_date: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "sessions": set(),
            "projects": set(),
            "input": 0,
            "output": 0,
            "cost": 0.0,
            "billed_cost": 0.0,
            "billed_covered": 0,
            "api_equivalent_cost": 0.0,
            "api_equivalent_covered": 0,
            "rows": 0,
        }
    )
    for r in rows:
        date = r["date"]
        g = by_date[date]
        g["sessions"].add(r["session"])
        g["projects"].add(r["project"])
        g["input"] += r["input"] + r["cache_read"] + r["cache_create"]
        g["output"] += r["output"]
        g["cost"] += r["cost"]
        g["rows"] += 1
        if r.get("billed_cost") is not None:
            g["billed_cost"] += r["billed_cost"]
            g["billed_covered"] += 1
        if r.get("api_equivalent_cost") is not None:
            g["api_equivalent_cost"] += r["api_equivalent_cost"]
            g["api_equivalent_covered"] += 1

    table = Table(show_header=True, pad_edge=False)
    table.add_column("Date")
    table.add_column("Sessions", justify="right")
    table.add_column("Projects")
    table.add_column("In", justify="right")
    table.add_column("Out", justify="right")
    table.add_column("Billed cost", justify="right")
    table.add_column("API-equivalent cost", justify="right")

    total_sessions = 0
    total_in = 0
    total_out = 0
    total_billed = 0.0
    total_api_equivalent = 0.0
    total_rows = 0
    total_billed_covered = 0
    total_api_covered = 0
    for date in sorted(by_date, reverse=True):
        g = by_date[date]
        projects = ", ".join(sorted(p for p in g["projects"] if p))
        if len(projects) > 30:
            projects = projects[:27] + "..."
        sess_count = len({s for s in g["sessions"] if s})
        total_sessions += sess_count
        total_in += g["input"]
        total_out += g["output"]
        total_billed += g["billed_cost"]
        total_api_equivalent += g["api_equivalent_cost"]
        total_rows += g["rows"]
        total_billed_covered += g["billed_covered"]
        total_api_covered += g["api_equivalent_covered"]
        billed_cell = _money_cell(g["billed_cost"], g["billed_covered"], g["rows"])
        api_cell = _money_cell(g["api_equivalent_cost"], g["api_equivalent_covered"], g["rows"])
        table.add_row(
            date,
            str(sess_count),
            projects,
            format_tokens(g["input"]),
            format_tokens(g["output"]),
            billed_cell,
            api_cell,
        )

    table.add_section()
    total_label = "Total (priced only)" if 0 < total_billed_covered < total_rows else "Total"
    table.add_row(
        total_label,
        str(total_sessions),
        "",
        format_tokens(total_in),
        format_tokens(total_out),
        _money_cell(total_billed, total_billed_covered, total_rows),
        _money_cell(total_api_equivalent, total_api_covered, total_rows),
        style="bold",
    )
    return Group(header, table)


def _money_cell(amount: float, covered: int, rows: int) -> str:
    if covered == 0:
        return "—"
    rendered = f"${round(amount, 2)}"
    return rendered if covered == rows else f"{rendered} ({covered}/{rows})"
