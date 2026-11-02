"""Inference rows are spend, never sessions (ADR-039 Evolution, 2026-11-01).

`run_inference` writes one `session_stats` row per billed call, keyed by the
provider's call id. Every reader that shows or divides by a session count must
leave those rows out, while every reader of tokens and cost must keep them.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from rich.console import Console

from lazy_harness.core.config import Config, MonitoringConfig, ProfileEntry, ProfilesConfig
from lazy_harness.monitoring import aggregate as agg_mod
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent

TODAY = datetime.now().strftime("%Y-%m-%d")


def _event(session: str, *, workload: str = "", output: int = 10, cost: float = 1.0) -> MetricEvent:
    return MetricEvent(
        event_id=f"e-{session}",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="u",
        tenant_id="t",
        profile="lazy",
        session=session,
        model="claude-haiku-4-5-20251001",
        project="p",
        date=TODAY,
        input_tokens=1,
        output_tokens=output,
        cache_read=0,
        cache_create=0,
        cost=cost,
        workload=workload,
        billing_model="per_token",
        cost_source="pricing",
        billed_cost=cost,
        billed_cost_source="pricing",
    )


@pytest.fixture
def db(tmp_path: Path):
    handle = MetricsDB(tmp_path / "m.db")
    handle.upsert_event(_event("real-1"))
    handle.upsert_event(_event("inf-1", workload="inference:distill", output=100, cost=2.0))
    handle.upsert_event(_event("inf-2", workload="inference:grade", output=1000, cost=4.0))
    yield handle
    handle.close()


def _text(renderable: object) -> str:
    console = Console(width=200, record=True, color_system=None)
    console.print(renderable)
    return console.export_text()


@pytest.mark.parametrize(
    "kwargs", [{"period": "all"}, {"period": TODAY[:7]}, {"period": "all", "since": TODAY}]
)
def test_aggregate_costs_counts_one_session_and_all_the_spend(db: MetricsDB, kwargs) -> None:
    totals = db.aggregate_costs(**kwargs)
    assert totals["session_count"] == 1
    assert totals["total_output"] == 10 + 100 + 1000
    assert totals["billed_cost"] == 7.0


def test_launch_ratio_denominator_leaves_inference_rows_out(db: MetricsDB) -> None:
    for _ in range(2):
        db.record_launch(profile="lazy", agent="claude-code", entry="run")
    ratio = db.launch_to_session_ratio(days=28)["lazy"]
    assert ratio.sessions == 1
    assert ratio.ratio == 2.0


def test_a_profile_with_only_inference_rows_has_no_ratio(tmp_path: Path) -> None:
    handle = MetricsDB(tmp_path / "only.db")
    try:
        handle.upsert_event(_event("inf-1", workload="inference:distill"))
        handle.record_launch(profile="lazy", agent="claude-code", entry="run")
        ratio = handle.launch_to_session_ratio(days=28)["lazy"]
    finally:
        handle.close()
    assert ratio.sessions == 0
    assert ratio.ratio is None


def test_aggregate_buckets_count_one_session_but_sum_all_the_spend(db: MetricsDB) -> None:
    agg = agg_mod.aggregate(db.query_stats(period="all"), ["workload"])
    assert agg.total.session_count == 1
    assert agg.total.output == 1110
    by_workload = {g.key["workload"]: g for g in agg.groups}
    assert by_workload["inference:distill"].session_count == 0
    assert by_workload["inference:distill"].output == 100
    assert by_workload["inference:grade"].output == 1000
    assert by_workload["unknown"].session_count == 1


def test_sessions_view_counts_one_session_and_keeps_the_tokens(db: MetricsDB) -> None:
    from lazy_harness.monitoring.views import sessions

    lines = [ln for ln in _text(sessions.render(db, "all")).splitlines() if "Total" in ln]
    assert re.search(r"Total\s*│\s*1\s", lines[0]), lines[0]
    assert "1.1K" in lines[0]


def test_costs_dashboard_counts_one_session(db: MetricsDB) -> None:
    from lazy_harness.monitoring import dashboard

    console = Console(width=200, record=True, color_system=None)
    dashboard.render_costs(db, console)
    row = next(ln for ln in console.export_text().splitlines() if TODAY in ln)
    assert re.search(rf"{TODAY}\s*│\s*1\s", row), row


def test_overview_dashboard_header_counts_one_session(db: MetricsDB) -> None:
    from lazy_harness.monitoring import dashboard

    console = Console(width=200, record=True, color_system=None)
    dashboard.render_overview(db, console)
    assert "Sessions: 1" in console.export_text()


def test_status_overview_counts_one_session_per_window(db: MetricsDB, tmp_path: Path) -> None:
    from lazy_harness.monitoring.views import overview
    from lazy_harness.monitoring.views._helpers import StatusContext

    prof_dir = tmp_path / "lazy"
    prof_dir.mkdir()
    cfg = Config(
        monitoring=MonitoringConfig(enabled=True),
        profiles=ProfilesConfig(
            default="lazy",
            items={"lazy": ProfileEntry(config_dir=str(prof_dir), roots=[])},
        ),
    )
    out = _text(overview.render(StatusContext.build(cfg), db))
    assert "1 today · 1 this month · 1 total" in out


def test_no_reader_in_src_counts_sessions_without_the_shared_predicate() -> None:
    """Audit: a new unfiltered session count fails here, naming the file."""
    src = Path(agg_mod.__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        text = path.read_text()
        if re.search(r"COUNT\(DISTINCT\s+session\)", text):
            offenders.append(f"{path.relative_to(src)}: unfiltered COUNT(DISTINCT session)")
        collects = re.search(
            r"""sessions\.add\(|\["(?:sessions|today|month|total)"\]\.add\(""", text
        )
        if collects and "counts_as_session" not in text:
            offenders.append(f"{path.relative_to(src)}: collects sessions without the predicate")
    assert offenders == []
