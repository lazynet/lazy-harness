"""Tests for the dimension/period aggregation behind `lh status tokens`."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from lazy_harness.monitoring.aggregate import (
    DIMENSIONS,
    FILTERABLE,
    aggregate,
    resolve_period,
)


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session": "s1",
        "date": "2026-08-12",
        "model": "claude-opus-5",
        "profile": "lazy",
        "project": "lazy-harness",
        "input": 100,
        "output": 10,
        "cache_read": 800,
        "cache_create": 100,
        "cost": 1.0,
    }
    base.update(overrides)
    return base


# --- resolve_period -------------------------------------------------------


def test_resolve_period_today_filters_on_todays_date() -> None:
    p = resolve_period("today")
    assert p.period == datetime.now().strftime("%Y-%m-%d")
    assert p.since is None
    assert p.label == "Today"


def test_resolve_period_week_uses_a_seven_day_since() -> None:
    p = resolve_period("week")
    assert p.since == (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    assert p.label == "Last 7 days"


def test_resolve_period_month_filters_on_the_current_year_month() -> None:
    p = resolve_period("month")
    assert p.period == datetime.now().strftime("%Y-%m")
    assert p.label == datetime.now().strftime("%B %Y")


def test_resolve_period_all_selects_every_row() -> None:
    p = resolve_period("all")
    assert p.period == "all"
    assert p.since is None
    assert p.label == "All time"


def test_resolve_period_accepts_an_n_day_window() -> None:
    p = resolve_period("30d")
    assert p.since == (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    assert p.label == "Last 30 days"


def test_resolve_period_accepts_an_explicit_year_month() -> None:
    p = resolve_period("2026-04")
    assert p.period == "2026-04"
    assert p.since is None
    assert p.label == "2026-04"


def test_resolve_period_accepts_an_explicit_day() -> None:
    p = resolve_period("2026-04-15")
    assert p.period == "2026-04-15"
    assert p.label == "2026-04-15"


# --- dimensions -----------------------------------------------------------


def test_every_documented_dimension_is_supported() -> None:
    assert set(DIMENSIONS) == {
        "profile",
        "project",
        "model",
        "day",
        "week",
        "month",
        "host",
        "workload",
    }


def test_grouping_by_profile_collapses_models_into_one_row() -> None:
    rows = [
        _row(model="claude-opus-5", cost=1.0),
        _row(model="claude-sonnet-5", cost=2.0, session="s2"),
    ]
    result = aggregate(rows, ["profile"])
    assert len(result.groups) == 1
    assert result.groups[0].key == {"profile": "lazy"}
    assert result.groups[0].cost == pytest.approx(3.0)


def test_grouping_by_day_uses_the_raw_date() -> None:
    rows = [_row(date="2026-08-12"), _row(date="2026-08-11", session="s2")]
    result = aggregate(rows, ["day"])
    assert [g.key["day"] for g in result.groups] == ["2026-08-11", "2026-08-12"]


def test_grouping_by_month_truncates_the_date() -> None:
    rows = [_row(date="2026-08-12"), _row(date="2026-07-30", session="s2")]
    result = aggregate(rows, ["month"])
    assert [g.key["month"] for g in result.groups] == ["2026-07", "2026-08"]


def test_grouping_by_week_uses_iso_week_numbering() -> None:
    # 2026-08-12 is a Wednesday in ISO week 33.
    result = aggregate([_row(date="2026-08-12")], ["week"])
    assert result.groups[0].key["week"] == "2026-W33"


def test_dimension_order_follows_the_order_requested() -> None:
    result = aggregate([_row()], ["month", "profile", "model"])
    assert list(result.groups[0].key) == ["month", "profile", "model"]
    assert result.dimensions == ["month", "profile", "model"]


def test_unknown_dimension_is_rejected() -> None:
    with pytest.raises(ValueError, match="quarter"):
        aggregate([_row()], ["quarter"])


def test_missing_dimension_value_falls_back_to_unknown() -> None:
    result = aggregate([_row(profile="")], ["profile"])
    assert result.groups[0].key == {"profile": "unknown"}


# --- token maths ----------------------------------------------------------


def test_reported_input_includes_both_cache_buckets() -> None:
    result = aggregate([_row(input=100, cache_read=800, cache_create=100)], ["profile"])
    assert result.groups[0].total_input == 1000


def test_cache_pct_is_cache_read_over_total_input() -> None:
    result = aggregate([_row(input=100, cache_read=800, cache_create=100)], ["profile"])
    assert result.groups[0].cache_pct == 80


def test_cache_pct_is_zero_when_there_are_no_input_tokens() -> None:
    result = aggregate([_row(input=0, cache_read=0, cache_create=0)], ["profile"])
    assert result.groups[0].cache_pct == 0


def test_sessions_are_counted_distinctly_across_models() -> None:
    rows = [
        _row(session="s1", model="claude-opus-5"),
        _row(session="s1", model="claude-sonnet-5"),
        _row(session="s2", model="claude-opus-5"),
    ]
    result = aggregate(rows, ["profile"])
    assert result.groups[0].session_count == 2


# --- filters --------------------------------------------------------------


def test_profile_filter_drops_non_matching_rows() -> None:
    rows = [_row(profile="lazy"), _row(profile="flex", session="s2")]
    result = aggregate(rows, ["profile"], {"profile": "lazy"})
    assert [g.key["profile"] for g in result.groups] == ["lazy"]


def test_filters_match_case_insensitive_substrings() -> None:
    rows = [
        _row(model="claude-opus-5"),
        _row(model="claude-opus-4-8", session="s2"),
        _row(model="claude-sonnet-5", session="s3"),
    ]
    result = aggregate(rows, ["model"], {"model": "OPUS"})
    assert [g.key["model"] for g in result.groups] == ["claude-opus-4-8", "claude-opus-5"]


def test_a_filter_that_matches_nothing_yields_no_groups() -> None:
    result = aggregate([_row(project="lazy-harness")], ["project"], {"project": "nope"})
    assert result.groups == []
    assert result.total.cost == 0.0


def test_filters_are_recorded_on_the_result() -> None:
    result = aggregate([_row()], ["profile"], {"profile": "lazy"})
    assert result.filters == {"profile": "lazy"}


def test_filtered_rows_are_excluded_from_the_total() -> None:
    rows = [_row(profile="lazy", cost=1.0), _row(profile="flex", cost=9.0, session="s2")]
    result = aggregate(rows, ["profile"], {"profile": "lazy"})
    assert result.total.cost == pytest.approx(1.0)


# --- subtotals ------------------------------------------------------------


def test_two_dimensions_produce_a_subtotal_per_leading_value() -> None:
    rows = [
        _row(profile="lazy", model="claude-opus-5", cost=1.0),
        _row(profile="lazy", model="claude-sonnet-5", cost=2.0, session="s2"),
        _row(profile="flex", model="claude-opus-5", cost=4.0, session="s3"),
    ]
    result = aggregate(rows, ["profile", "model"])
    assert [(s.key["profile"], s.cost) for s in result.subtotals] == [
        ("flex", pytest.approx(4.0)),
        ("lazy", pytest.approx(3.0)),
    ]


def test_a_single_dimension_produces_no_subtotals() -> None:
    result = aggregate([_row(), _row(session="s2")], ["profile"])
    assert result.subtotals == []


def test_subtotals_key_only_on_the_first_dimension() -> None:
    result = aggregate([_row()], ["profile", "model", "day"])
    assert result.subtotals[0].key == {"profile": "lazy"}


def test_subtotal_sessions_are_distinct_across_its_groups() -> None:
    rows = [
        _row(profile="lazy", model="claude-opus-5", session="s1"),
        _row(profile="lazy", model="claude-sonnet-5", session="s1"),
    ]
    result = aggregate(rows, ["profile", "model"])
    assert result.subtotals[0].session_count == 1


# --- precision ------------------------------------------------------------


def test_total_is_not_degraded_by_per_group_rounding() -> None:
    """Regression: the view used to round each group before summing.

    Sixteen groups of $0.005 must total $0.08, not $0.00 (round-then-sum) and
    not $0.16 (round-half-up per group).
    """
    rows = [_row(model=f"m{i}", session=f"s{i}", cost=0.005) for i in range(16)]
    result = aggregate(rows, ["model"])
    assert result.total.cost == pytest.approx(0.08)


def test_total_matches_the_sum_of_every_group() -> None:
    rows = [_row(session=f"s{i}", model=f"m{i}", cost=0.1) for i in range(10)]
    result = aggregate(rows, ["model"])
    assert result.total.cost == pytest.approx(sum(g.cost for g in result.groups))


def test_aggregated_total_matches_the_databases_own_sum(tmp_path: Any) -> None:
    """Regression contract: the two read paths must agree on the total.

    `lh metrics status` reports `db.aggregate_costs()` (a SQL SUM) while
    `lh status tokens` reports this module's total. They read the same table
    and must not disagree.
    """
    from lazy_harness.monitoring.db import MetricsDB

    entries = [
        {
            "session": f"s{i}",
            "date": "2026-08-12",
            "model": f"m{i % 3}",
            "profile": "lazy" if i % 2 else "flex",
            "project": "p",
            "input": 100,
            "output": 10,
            "cache_read": 800,
            "cache_create": 100,
            "cost": 0.005 * i,
        }
        for i in range(20)
    ]
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_stats(entries)
        expected = db.aggregate_costs(period="all")
        rows = db.query_stats(period="all")
    finally:
        db.close()

    result = aggregate(rows, ["profile", "model"])
    assert round(result.total.cost, 2) == expected["total_cost"]
    assert result.total.session_count == expected["session_count"]


def test_aggregate_groups_by_host() -> None:
    rows = [
        _row(session="s1", host="LazyMBP", cost=1.0),
        _row(session="s2", host="agents", cost=2.0),
        _row(session="s3", host="agents", cost=4.0),
    ]
    result = aggregate(rows, ["host"])
    by_host = {g.key["host"]: g.cost for g in result.groups}
    assert by_host == {"LazyMBP": 1.0, "agents": 6.0}


def test_aggregate_groups_by_workload() -> None:
    rows = [
        _row(session="s1", workload="vault-pass", cost=1.0),
        _row(session="s2", workload="vault-pass", cost=2.0),
        _row(session="s3", workload="", cost=4.0),
    ]
    result = aggregate(rows, ["workload"])
    by_workload = {g.key["workload"]: g.cost for g in result.groups}
    assert by_workload == {"vault-pass": 3.0, "unknown": 4.0}


def test_host_and_workload_are_filterable() -> None:
    assert set(FILTERABLE) == {"profile", "project", "model", "host", "workload"}


def test_aggregate_filters_by_workload() -> None:
    rows = [
        _row(session="s1", workload="vault-pass", cost=1.0),
        _row(session="s2", workload="other", cost=9.0),
    ]
    result = aggregate(rows, ["workload"], {"workload": "vault"})
    assert result.total.cost == 1.0


def test_aggregate_crosses_host_with_workload() -> None:
    rows = [
        _row(session="s1", host="agents", workload="vault-pass", cost=1.0),
        _row(session="s2", host="agents", workload="vault-pass", cost=2.0),
        _row(session="s3", host="LazyMBP", workload="vault-pass", cost=4.0),
    ]
    result = aggregate(rows, ["host", "workload"])
    keys = {(g.key["host"], g.key["workload"]): g.cost for g in result.groups}
    assert keys == {("agents", "vault-pass"): 3.0, ("LazyMBP", "vault-pass"): 4.0}
