"""`lh status tokens` view — renders a token / cost breakdown.

Aggregation lives in `lazy_harness.monitoring.aggregate`; this module only turns
an `Aggregation` into a table or into JSON.
"""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.table import Table

from lazy_harness.monitoring.aggregate import Aggregation, Bucket, Period
from lazy_harness.monitoring.views._helpers import format_tokens

SUBTOTAL_LABEL = "subtotal"


def _cost_cell(bucket: Bucket) -> str:
    return "—" if bucket.all_flat_rate else f"${round(bucket.cost, 2)}"


def _measures(bucket: Bucket) -> list[str]:
    return [
        format_tokens(bucket.total_input),
        format_tokens(bucket.output),
        f"{bucket.cache_pct}%",
        _cost_cell(bucket),
    ]


def render_table(agg: Aggregation, period: Period) -> RenderableType:
    header = " › ".join(agg.dimensions)
    filters = " ".join(f"{k}~{v}" for k, v in agg.filters.items())
    title = f"[bold]By: {header} | Period: {period.label}"
    if filters:
        title += f" | Filter: {filters}"
    title += f" | {agg.total.session_count} sessions[/bold]\n"
    if not agg.groups:
        return Group(title, "[dim]No data.[/dim]")

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
    # A total spanning both billing models still sums to the right number —
    # a flat_rate row's cost is 0.0 — but the label must say the total is not
    # every profile's real spend, only the metered part of it.
    priced_only = (
        "flat_rate" in agg.total.billing_models and "per_token" in agg.total.billing_models
    )
    total_label = "Total (priced only)" if priced_only else "Total"
    table.add_row(
        total_label,
        *[""] * (len(agg.dimensions) - 1),
        *_measures(agg.total),
        style="bold",
    )
    return Group(title, table)


def _add_subtotal(table: Table, agg: Aggregation, bucket: Bucket) -> None:
    if not agg.subtotals:
        return
    label_cells = [bucket.key[agg.dimensions[0]], SUBTOTAL_LABEL]
    label_cells += [""] * (len(agg.dimensions) - 2)
    table.add_row(*label_cells, *_measures(bucket), style="dim bold")


def _bucket_json(bucket: Bucket, *, with_key: bool = True) -> dict[str, Any]:
    # A machine consumer distinguishes "no rows" from "subscription usage"
    # without parsing the render: null cost plus cost_source, never $0.00.
    payload: dict[str, Any] = {
        "input": bucket.total_input,
        "output": bucket.output,
        "cache_read": bucket.cache_read,
        "cache_create": bucket.cache_create,
        "cache_pct": bucket.cache_pct,
        "cost": None if bucket.all_flat_rate else round(bucket.cost, 2),
        "cost_source": "subscription" if bucket.all_flat_rate else None,
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
