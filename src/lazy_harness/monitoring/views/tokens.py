"""`lh status tokens` view — token / cost breakdown grouped by project or model."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from rich.console import Console
from rich.table import Table

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.views._helpers import format_tokens
from lazy_harness.monitoring.views.sessions import _period_label, _query_for_period


def _aggregate(rows: list[dict[str, Any]], group_by: str) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "input": 0.0,
                "output": 0.0,
                "cache_read": 0.0,
                "cache_create": 0.0,
                "cost": 0.0,
            }
        )
    )
    for entry in rows:
        group = entry.get(group_by) or "unknown"
        model = entry.get("model") or "unknown"
        agg = groups[group][model]
        agg["input"] += entry.get("input", 0)
        agg["output"] += entry.get("output", 0)
        agg["cache_read"] += entry.get("cache_read", 0)
        agg["cache_create"] += entry.get("cache_create", 0)
        agg["cost"] += entry.get("cost", 0)

    out: list[dict[str, Any]] = []
    for group_name in sorted(groups):
        for model_name in sorted(groups[group_name]):
            t = groups[group_name][model_name]
            total_input = t["input"] + t["cache_read"] + t["cache_create"]
            cache_pct = int(t["cache_read"] * 100 / total_input) if total_input > 0 else 0
            out.append(
                {
                    "group": group_name,
                    "model": model_name,
                    "input": int(total_input),
                    "output": int(t["output"]),
                    "cache_pct": cache_pct,
                    "cost": round(t["cost"], 2),
                }
            )
    return out


def render(db: MetricsDB, console: Console, period: str, group_by: str) -> None:
    console.print(f"[bold]By: {group_by} | Period: {_period_label(period)}[/bold]\n")
    rows = _query_for_period(db, period)
    if not rows:
        console.print("[dim]No data.[/dim]")
        return

    agg = _aggregate(rows, group_by)
    table = Table(show_header=True, pad_edge=False)
    table.add_column(group_by.title())
    table.add_column("Model")
    table.add_column("In", justify="right")
    table.add_column("Out", justify="right")
    table.add_column("Cache%", justify="right")
    table.add_column("Cost", justify="right")

    total_cost = 0.0
    for r in agg:
        total_cost += r["cost"]
        table.add_row(
            r["group"],
            r["model"],
            format_tokens(r["input"]),
            format_tokens(r["output"]),
            f"{r['cache_pct']}%",
            f"${r['cost']}",
        )

    table.add_section()
    table.add_row("", "", "", "", "Total:", f"${round(total_cost, 2)}", style="bold")
    console.print(table)
