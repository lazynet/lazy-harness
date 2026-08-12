"""`lh status tokens` view — renders a token / cost breakdown.

Aggregation lives in `lazy_harness.monitoring.aggregate`; this module only turns
an `Aggregation` into a table or into JSON.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table

from lazy_harness.monitoring.aggregate import Aggregation, Bucket, Period
from lazy_harness.monitoring.views._helpers import format_tokens

SUBTOTAL_LABEL = "subtotal"


def _measures(bucket: Bucket) -> list[str]:
    return [
        format_tokens(bucket.total_input),
        format_tokens(bucket.output),
        f"{bucket.cache_pct}%",
        f"${round(bucket.cost, 2)}",
    ]


def render_table(agg: Aggregation, period: Period, console: Console) -> None:
    header = " › ".join(agg.dimensions)
    filters = " ".join(f"{k}~{v}" for k, v in agg.filters.items())
    title = f"[bold]By: {header} | Period: {period.label}"
    if filters:
        title += f" | Filter: {filters}"
    title += f" | {agg.total.session_count} sessions[/bold]\n"
    console.print(title)

    if not agg.groups:
        console.print("[dim]No data.[/dim]")
        return

    table = Table(show_header=True, pad_edge=False)
    for dimension in agg.dimensions:
        table.add_column(dimension.title())
    table.add_column("In", justify="right")
    table.add_column("Out", justify="right")
    table.add_column("Cache%", justify="right")
    table.add_column("Cost", justify="right")

    subtotals = {s.key[agg.dimensions[0]]: s for s in agg.subtotals}
    lead = agg.dimensions[0]
    previous: str | None = None

    for group in agg.groups:
        current = group.key[lead]
        if previous is not None and current != previous and previous in subtotals:
            _add_subtotal(table, agg, subtotals[previous])
        table.add_row(*[group.key[d] for d in agg.dimensions], *_measures(group))
        previous = current

    if previous is not None and previous in subtotals:
        _add_subtotal(table, agg, subtotals[previous])

    table.add_section()
    table.add_row(
        "Total",
        *[""] * (len(agg.dimensions) - 1),
        *_measures(agg.total),
        style="bold",
    )
    console.print(table)


def _add_subtotal(table: Table, agg: Aggregation, bucket: Bucket) -> None:
    if not agg.subtotals:
        return
    label_cells = [bucket.key[agg.dimensions[0]], SUBTOTAL_LABEL]
    label_cells += [""] * (len(agg.dimensions) - 2)
    table.add_row(*label_cells, *_measures(bucket), style="dim bold")


def _bucket_json(bucket: Bucket, *, with_key: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "input": bucket.total_input,
        "output": bucket.output,
        "cache_read": bucket.cache_read,
        "cache_create": bucket.cache_create,
        "cache_pct": bucket.cache_pct,
        "cost": round(bucket.cost, 2),
        "sessions": bucket.session_count,
    }
    if with_key:
        return {"key": bucket.key, **payload}
    return payload


def render_json(agg: Aggregation, period: Period, console: Console) -> None:
    payload = {
        "period": {"spec": period.spec, "label": period.label, "since": period.since},
        "dimensions": agg.dimensions,
        "filters": agg.filters,
        "groups": [_bucket_json(g) for g in agg.groups],
        "subtotals": [_bucket_json(s) for s in agg.subtotals],
        "total": _bucket_json(agg.total, with_key=False),
    }
    console.print_json(json.dumps(payload))
