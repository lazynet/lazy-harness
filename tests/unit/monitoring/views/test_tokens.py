"""Tests for the `lh status tokens` table."""

from __future__ import annotations

from lazy_harness.monitoring.aggregate import aggregate, resolve_period
from lazy_harness.monitoring.views import tokens as tokens_view

from ._render import render_to_text


def _rendered(rows: list[dict], dims: list[str]) -> str:
    period = resolve_period("month")
    agg = aggregate(rows, dims, {"profile": "", "model": "", "project": ""})
    return render_to_text(tokens_view.render_table(agg, period))


def test_tokens_keeps_the_header_when_there_is_no_data() -> None:
    """The empty case still has to say what it was grouping and over what
    period, or the reader cannot tell an empty result from a wrong query."""
    text = _rendered([], ["project"])

    assert "By: project" in text
    assert "No data" in text


def test_tokens_groups_by_the_requested_dimension() -> None:
    rows = [
        {
            "project": "alpha",
            "model": "opus",
            "profile": "lazy",
            "input": 10,
            "output": 5,
            "cost": 0.5,
            "session": "s1",
        },
        {
            "project": "beta",
            "model": "opus",
            "profile": "lazy",
            "input": 20,
            "output": 7,
            "cost": 1.0,
            "session": "s2",
        },
    ]

    text = _rendered(rows, ["project"])

    assert "alpha" in text
    assert "beta" in text
    assert "2 sessions" in text


# --- billing model (ADR-050) -------------------------------------------------


def test_tokens_group_renders_a_dash_when_it_is_entirely_flat_rate() -> None:
    rows = [
        {
            "project": "a",
            "model": "opus",
            "profile": "beta",
            "input": 10,
            "output": 5,
            "cost": 0.0,
            "session": "s1",
            "billing_model": "flat_rate",
        },
    ]
    text = _rendered(rows, ["profile"])
    assert "—" in text
    assert "$0.0" not in text


def test_tokens_total_relabeled_priced_only_when_billing_models_are_mixed() -> None:
    rows = [
        {
            "project": "a",
            "model": "opus",
            "profile": "lazy",
            "input": 10,
            "output": 5,
            "cost": 1.0,
            "session": "s1",
            "billing_model": "per_token",
        },
        {
            "project": "b",
            "model": "opus",
            "profile": "beta",
            "input": 20,
            "output": 7,
            "cost": 0.0,
            "session": "s2",
            "billing_model": "flat_rate",
        },
    ]
    text = _rendered(rows, ["profile"])
    assert "priced only" in text


def test_tokens_total_not_relabeled_when_every_row_is_per_token() -> None:
    rows = [
        {
            "project": "a",
            "model": "opus",
            "profile": "lazy",
            "input": 10,
            "output": 5,
            "cost": 1.0,
            "session": "s1",
        },
    ]
    text = _rendered(rows, ["profile"])
    assert "priced only" not in text


def test_tokens_json_reports_null_cost_and_subscription_source_for_a_flat_rate_group() -> None:
    import io
    import json

    from rich.console import Console

    rows = [
        {
            "project": "a",
            "model": "opus",
            "profile": "beta",
            "input": 10,
            "output": 5,
            "cost": 0.0,
            "session": "s1",
            "billing_model": "flat_rate",
        },
    ]
    period = resolve_period("month")
    agg = aggregate(rows, ["profile"])

    buf = io.StringIO()
    console = Console(file=buf, width=120, force_terminal=False, no_color=True)
    tokens_view.render_json(agg, period, console)
    payload = json.loads(buf.getvalue())

    assert payload["total"]["cost"] is None
    assert payload["total"]["cost_source"] == "subscription"
    assert payload["groups"][0]["cost"] is None
    assert payload["groups"][0]["cost_source"] == "subscription"


def test_tokens_json_reports_numeric_cost_and_no_source_for_a_per_token_group() -> None:
    import io
    import json

    from rich.console import Console

    rows = [
        {
            "project": "a",
            "model": "opus",
            "profile": "lazy",
            "input": 10,
            "output": 5,
            "cost": 1.0,
            "session": "s1",
        },
    ]
    period = resolve_period("month")
    agg = aggregate(rows, ["profile"])

    buf = io.StringIO()
    console = Console(file=buf, width=120, force_terminal=False, no_color=True)
    tokens_view.render_json(agg, period, console)
    payload = json.loads(buf.getvalue())

    assert payload["total"]["cost"] == 1.0
    assert payload["total"]["cost_source"] is None
