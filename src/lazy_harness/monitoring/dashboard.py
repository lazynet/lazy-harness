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
        f"Billed cost: ${totals['billed_cost']}",
        "API-equivalent cost: "
        + (
            f"${totals['api_equivalent_cost']}"
            if totals["api_equivalent_cost"] is not None
            else "—"
        ),
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
            by_date[date] = {
                "sessions": set(),
                "input": 0,
                "output": 0,
                "billed_cost": 0.0,
                "api_equivalent_cost": 0.0,
                "billed_covered": 0,
                "api_covered": 0,
                "rows": 0,
            }
        by_date[date]["sessions"].add(r["session"])
        by_date[date]["input"] += r["input"] + r["cache_read"] + r["cache_create"]
        by_date[date]["output"] += r["output"]
        by_date[date]["rows"] += 1
        if r.get("billed_cost") is not None:
            by_date[date]["billed_cost"] += r["billed_cost"]
            by_date[date]["billed_covered"] += 1
        if r.get("api_equivalent_cost") is not None:
            by_date[date]["api_equivalent_cost"] += r["api_equivalent_cost"]
            by_date[date]["api_covered"] += 1

    table = Table(show_header=True, pad_edge=False)
    table.add_column("Date")
    table.add_column("Sessions", justify="right")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Billed cost", justify="right")
    table.add_column("API-equivalent cost", justify="right")

    total_billed = 0.0
    total_api = 0.0
    total_rows = total_billed_covered = total_api_covered = 0
    for date in sorted(by_date, reverse=True):
        d = by_date[date]
        total_billed += d["billed_cost"]
        total_api += d["api_equivalent_cost"]
        total_rows += d["rows"]
        total_billed_covered += d["billed_covered"]
        total_api_covered += d["api_covered"]
        table.add_row(
            date,
            str(len(d["sessions"])),
            format_tokens(d["input"]),
            format_tokens(d["output"]),
            _money(d["billed_cost"], d["billed_covered"], d["rows"]),
            _money(d["api_equivalent_cost"], d["api_covered"], d["rows"]),
        )

    table.add_section()
    table.add_row(
        "Total",
        "",
        "",
        "",
        _money(total_billed, total_billed_covered, total_rows),
        _money(total_api, total_api_covered, total_rows),
        style="bold",
    )
    console.print(table)


def _money(amount: float, covered: int, rows: int) -> str:
    if covered == 0:
        return "—"
    rendered = f"${round(amount, 2)}"
    return rendered if covered == rows else f"{rendered} ({covered}/{rows})"
