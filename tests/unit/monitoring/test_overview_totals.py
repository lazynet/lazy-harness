"""Tests for the numeric totals rendered by the `lh status` overview."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from lazy_harness.core.config import Config, MonitoringConfig, ProfileEntry, ProfilesConfig
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.views import overview
from lazy_harness.monitoring.views._helpers import StatusContext


def _render(db: MetricsDB, cfg: Config) -> str:
    ctx = StatusContext.build(cfg)
    console = Console(width=200, record=True, color_system=None)
    overview.render(ctx, db, console)
    return console.export_text()


def _cfg(tmp_path: Path) -> Config:
    prof_dir = tmp_path / "lazy"
    prof_dir.mkdir()
    return Config(
        monitoring=MonitoringConfig(enabled=True),
        profiles=ProfilesConfig(
            default="lazy",
            items={"lazy": ProfileEntry(config_dir=str(prof_dir), roots=[])},
        ),
    )


def _cfg_two(tmp_path: Path) -> Config:
    for name in ("lazy", "flex"):
        (tmp_path / name).mkdir()
    return Config(
        monitoring=MonitoringConfig(enabled=True),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir=str(tmp_path / "lazy"), roots=[]),
                "flex": ProfileEntry(config_dir=str(tmp_path / "flex"), roots=[]),
            },
        ),
    )


def test_tokens_line_shows_input_only_not_cache(tmp_path: Path) -> None:
    """Overview 'Tokens' row must report input_tokens alone, not input+cache.

    Prior bug: the row summed input + cache_read + cache_create, which
    inflated the 'in' number by orders of magnitude on sessions with heavy
    prompt caching. ccusage and Anthropic's billing report them as
    separate buckets; we match that.
    """
    from datetime import datetime

    month_str = datetime.now().strftime("%Y-%m")
    cfg = _cfg(tmp_path)
    db = MetricsDB(tmp_path / "metrics.db")
    db.upsert_stats(
        [
            {
                "session": "s1",
                "date": f"{month_str}-01",
                "model": "claude-opus-4-6",
                "profile": "lazy",
                "project": "x",
                "input": 1000,
                "output": 500,
                "cache_read": 900_000,  # huge cache
                "cache_create": 100_000,
                "cost": 1.23,
            }
        ]
    )

    out = _render(db, cfg)
    db.close()

    # The 'Tokens' row must show the 1000 raw inputs, not the 1M-ish
    # conflated total.
    tokens_line = next(line for line in out.splitlines() if "Tokens" in line)
    assert "1000" in tokens_line or "1.0K" in tokens_line
    assert "1.0M" not in tokens_line  # would indicate cache got summed in
    assert "$1.23" in tokens_line


def test_overview_splits_sessions_and_tokens_per_profile(tmp_path: Path) -> None:
    """Sessions and Tokens rows must break down per profile with an 'all' totalizer."""
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")
    cfg = _cfg_two(tmp_path)
    db = MetricsDB(tmp_path / "metrics.db")
    db.upsert_stats(
        [
            {
                "session": "lazy-s1",
                "date": today,
                "model": "claude-opus-4-6",
                "profile": "lazy",
                "project": "p",
                "input": 100,
                "output": 50,
                "cache_read": 0,
                "cache_create": 0,
                "cost": 1.00,
            },
            {
                "session": "lazy-s2",
                "date": f"{month}-01",
                "model": "claude-opus-4-6",
                "profile": "lazy",
                "project": "p",
                "input": 200,
                "output": 80,
                "cache_read": 0,
                "cache_create": 0,
                "cost": 2.00,
            },
            {
                "session": "flex-s1",
                "date": today,
                "model": "claude-opus-4-6",
                "profile": "flex",
                "project": "p",
                "input": 300,
                "output": 120,
                "cache_read": 0,
                "cache_create": 0,
                "cost": 3.00,
            },
        ]
    )

    out = _render(db, cfg)
    db.close()
    lines = out.splitlines()

    # Sessions: one line per profile + 'all'
    sess_lazy = next(line for line in lines if "lazy" in line and "today" in line)
    assert "1 today" in sess_lazy and "2 this month" in sess_lazy
    sess_flex = next(line for line in lines if "flex" in line and "today" in line)
    assert "1 today" in sess_flex and "1 this month" in sess_flex
    sess_all = next(line for line in lines if "all" in line and "today" in line)
    assert "2 today" in sess_all and "3 this month" in sess_all

    # Tokens: one line per profile + 'all'
    tok_lazy = next(line for line in lines if "lazy" in line and "$" in line)
    assert "$3.0" in tok_lazy
    tok_flex = next(line for line in lines if "flex" in line and "$" in line)
    assert "$3.0" in tok_flex
    tok_all = next(line for line in lines if "all" in line and "$" in line)
    assert "$6.0" in tok_all
