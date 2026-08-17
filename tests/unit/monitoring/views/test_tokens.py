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
