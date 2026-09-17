"""Tests for the `lh status sessions` view (ADR-050 billing-model rendering)."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.views import sessions as sessions_view

from ._render import render_to_text


def test_sessions_day_renders_a_dash_when_entirely_flat_rate(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_stats(
            [
                {
                    "session": "s1",
                    "date": "2026-04-14",
                    "model": "sonnet",
                    "profile": "beta",
                    "project": "p",
                    "input": 100,
                    "output": 50,
                    "cost": 0.0,
                    "billing_model": "flat_rate",
                }
            ]
        )
        text = render_to_text(sessions_view.render(db, "all"))
    finally:
        db.close()
    assert "—" in text
    assert "$0.0" not in text


def test_sessions_total_relabeled_priced_only_when_billing_models_are_mixed(
    tmp_path: Path,
) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_stats(
            [
                {
                    "session": "s1",
                    "date": "2026-04-14",
                    "model": "sonnet",
                    "profile": "lazy",
                    "project": "p",
                    "input": 100,
                    "output": 50,
                    "cost": 1.0,
                    "billing_model": "per_token",
                },
                {
                    "session": "s2",
                    "date": "2026-04-15",
                    "model": "sonnet",
                    "profile": "beta",
                    "project": "p",
                    "input": 100,
                    "output": 50,
                    "cost": 0.0,
                    "billing_model": "flat_rate",
                },
            ]
        )
        text = render_to_text(sessions_view.render(db, "all"))
    finally:
        db.close()
    assert "priced only" in text


def test_sessions_total_not_relabeled_when_every_row_is_per_token(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_stats(
            [
                {
                    "session": "s1",
                    "date": "2026-04-14",
                    "model": "sonnet",
                    "profile": "lazy",
                    "project": "p",
                    "input": 100,
                    "output": 50,
                    "cost": 1.0,
                }
            ]
        )
        text = render_to_text(sessions_view.render(db, "all"))
    finally:
        db.close()
    assert "priced only" not in text
