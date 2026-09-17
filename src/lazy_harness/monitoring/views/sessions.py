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
    header = f"[bold]Period: {_period_label(period)}[/bold]\n"
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
            "billing_models": set(),
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
        g["billing_models"].add(r.get("billing_model") or "per_token")

    table = Table(show_header=True, pad_edge=False)
    table.add_column("Date")
    table.add_column("Sessions", justify="right")
    table.add_column("Projects")
    table.add_column("In", justify="right")
    table.add_column("Out", justify="right")
    table.add_column("Cost", justify="right")

    total_sessions = 0
    total_in = 0
    total_out = 0
    total_cost = 0.0
    total_billing_models: set[str] = set()
    for date in sorted(by_date, reverse=True):
        g = by_date[date]
        projects = ", ".join(sorted(p for p in g["projects"] if p))
        if len(projects) > 30:
            projects = projects[:27] + "..."
        sess_count = len({s for s in g["sessions"] if s})
        cost = round(g["cost"], 2)
        total_sessions += sess_count
        total_in += g["input"]
        total_out += g["output"]
        total_cost += cost
        total_billing_models |= g["billing_models"]
        cost_cell = "—" if g["billing_models"] == {"flat_rate"} else f"${cost}"
        table.add_row(
            date,
            str(sess_count),
            projects,
            format_tokens(g["input"]),
            format_tokens(g["output"]),
            cost_cell,
        )

    table.add_section()
    priced_only = "flat_rate" in total_billing_models and "per_token" in total_billing_models
    total_cost_cell = "—" if total_billing_models == {"flat_rate"} else f"${round(total_cost, 2)}"
    table.add_row(
        "Total (priced only)" if priced_only else "Total",
        str(total_sessions),
        "",
        format_tokens(total_in),
        format_tokens(total_out),
        total_cost_cell,
        style="bold",
    )
    return Group(header, table)
