"""`lh status sessions` view — daily breakdown of sessions, tokens, cost."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from rich.console import Console
from rich.table import Table

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.views._helpers import format_tokens


def _period_label(period: str) -> str:
    today = datetime.now()
    if period == "today":
        return "Today"
    if period == "week":
        return "Last 7 days"
    if period == "month":
        return today.strftime("%B %Y")
    if period == "all":
        return "All time"
    return period


def _query_for_period(db: MetricsDB, period: str) -> list[dict[str, Any]]:
    today = datetime.now()
    if period == "today":
        return db.query_stats(period=today.strftime("%Y-%m-%d"))
    if period == "week":
        since = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        return db.query_stats(since=since)
    if period == "month":
        return db.query_stats(period=today.strftime("%Y-%m"))
    if period == "all":
        return db.query_stats(period="all")
    return db.query_stats(period=period)


def render(db: MetricsDB, console: Console, period: str) -> None:
    console.print(f"[bold]Period: {_period_label(period)}[/bold]\n")
    rows = _query_for_period(db, period)
    if not rows:
        console.print("[dim]No data. Run a session first.[/dim]")
        return

    by_date: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"sessions": set(), "projects": set(), "input": 0, "output": 0, "cost": 0.0}
    )
    for r in rows:
        date = r["date"]
        g = by_date[date]
        g["sessions"].add(r["session"])
        g["projects"].add(r["project"])
        g["input"] += r["input"] + r["cache_read"] + r["cache_create"]
        g["output"] += r["output"]
        g["cost"] += r["cost"]

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
        table.add_row(
            date,
            str(sess_count),
            projects,
            format_tokens(g["input"]),
            format_tokens(g["output"]),
            f"${cost}",
        )

    table.add_section()
    table.add_row(
        "Total",
        str(total_sessions),
        "",
        format_tokens(total_in),
        format_tokens(total_out),
        f"${round(total_cost, 2)}",
        style="bold",
    )
    console.print(table)
