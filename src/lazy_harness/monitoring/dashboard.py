"""Rich TUI dashboard for monitoring."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lazy_harness.monitoring.db import MetricsDB


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def render_overview(db: MetricsDB, console: Console) -> None:
    totals = db.aggregate_costs(period="all")
    if totals["session_count"] == 0:
        console.print("No data yet. Run some sessions first.")
        return
    lines: list[str] = [
        f"Sessions: {totals['session_count']}",
        f"Tokens in: {format_tokens(totals['total_input'])}",
        f"Tokens out: {format_tokens(totals['total_output'])}",
        f"Total cost: ${totals['total_cost']}",
    ]
    panel = Panel("\n".join(lines), title="lh status", border_style="bold")
    console.print(panel)


def render_costs(
    db: MetricsDB, console: Console, period: str = "all", since: str | None = None
) -> None:
    rows = db.query_stats(period=period, since=since)
    if not rows:
        console.print("No data for this period.")
        return

    by_date: dict[str, dict[str, Any]] = {}
    for r in rows:
        date = r["date"]
        if date not in by_date:
            by_date[date] = {"sessions": set(), "input": 0, "output": 0, "cost": 0.0}
        by_date[date]["sessions"].add(r["session"])
        by_date[date]["input"] += r["input"] + r["cache_read"] + r["cache_create"]
        by_date[date]["output"] += r["output"]
        by_date[date]["cost"] += r["cost"]

    table = Table(show_header=True, pad_edge=False)
    table.add_column("Date")
    table.add_column("Sessions", justify="right")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cost", justify="right")

    total_cost = 0.0
    for date in sorted(by_date, reverse=True):
        d = by_date[date]
        cost = round(d["cost"], 2)
        total_cost += cost
        table.add_row(
            date,
            str(len(d["sessions"])),
            format_tokens(d["input"]),
            format_tokens(d["output"]),
            f"${cost}",
        )

    table.add_section()
    table.add_row("Total", "", "", "", f"${round(total_cost, 2)}", style="bold")
    console.print(table)
