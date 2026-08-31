"""Integration tests for `lh metrics ingest`."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    MonitoringConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)


def _write_session(profile_dir: Path, project_slug: str, uuid: str) -> None:
    d = profile_dir / "projects" / project_slug
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{uuid}.jsonl"
    with open(f, "w") as fh:
        fh.write(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "model": "claude-opus-4-6",
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        },
                    },
                    "timestamp": "2026-04-13T10:00:00",
                }
            )
            + "\n"
        )


def _setup(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    db_path = home_dir / ".local" / "share" / "lazy-harness" / "metrics.db"
    profile_dir = home_dir / ".claude-lazy"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={"lazy": ProfileEntry(config_dir=str(profile_dir), roots=["~"])},
        ),
        monitoring=MonitoringConfig(enabled=True, db=str(db_path)),
    )
    save_config(cfg, config_path)
    profile_dir.mkdir(parents=True, exist_ok=True)
    return db_path


def test_metrics_ingest_populates_db(home_dir: Path) -> None:
    db_path = _setup(home_dir)
    _write_session(
        home_dir / ".claude-lazy",
        "-tmp-proj",
        "11111111-1111-1111-1111-111111111111",
    )

    result = CliRunner().invoke(cli, ["metrics", "ingest"])
    assert result.exit_code == 0, result.output
    assert "updated" in result.output.lower()

    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(db_path)
    rows = db.query_stats(period="all")
    db.close()
    assert len(rows) == 1
    assert rows[0]["input"] == 100


def test_metrics_ingest_dry_run_writes_nothing(home_dir: Path) -> None:
    db_path = _setup(home_dir)
    _write_session(
        home_dir / ".claude-lazy",
        "-tmp-proj",
        "22222222-2222-2222-2222-222222222222",
    )

    result = CliRunner().invoke(cli, ["metrics", "ingest", "--dry-run"])
    assert result.exit_code == 0, result.output

    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(db_path)
    rows = db.query_stats(period="all")
    db.close()
    assert rows == []


# --- backfill-host ----------------------------------------------------------


def _v1_row(db_path: Path, session: str) -> None:
    """One stats row as the store held it before ADR-037: host empty."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.event_id import derive_event_id
    from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent

    db = MetricsDB(db_path)
    try:
        db.upsert_event(
            MetricEvent(
                event_id=derive_event_id(profile="lazy", session=session, model="opus"),
                schema_version=METRIC_EVENT_SCHEMA_VERSION,
                user_id="lazynet",
                tenant_id="local",
                profile="lazy",
                session=session,
                model="opus",
                project="demo",
                date="2026-07-01",
                input_tokens=10,
                output_tokens=5,
                cache_read=0,
                cache_create=0,
                cost=0.25,
                host="",
            )
        )
    finally:
        db.close()


def test_metrics_backfill_host_stamps_rows_without_one(home_dir: Path) -> None:
    """No --host: the command resolves the local one itself. Always passing it
    would leave the default resolution — the only path a real run takes —
    untested."""
    db_path = _setup(home_dir)
    _v1_row(db_path, "s-old")

    result = CliRunner().invoke(cli, ["metrics", "backfill-host"])
    assert result.exit_code == 0, result.output

    from lazy_harness.core.identity import resolve_host
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(db_path)
    rows = db.query_stats(period="all")
    db.close()
    assert rows[0]["host"] == resolve_host()


def test_metrics_backfill_host_honours_an_explicit_host(home_dir: Path) -> None:
    db_path = _setup(home_dir)
    _v1_row(db_path, "s-old")

    result = CliRunner().invoke(cli, ["metrics", "backfill-host", "--host", "CT145"])
    assert result.exit_code == 0, result.output

    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(db_path)
    rows = db.query_stats(period="all")
    db.close()
    assert rows[0]["host"] == "CT145"


def test_metrics_backfill_host_dry_run_writes_nothing(home_dir: Path) -> None:
    """The count is reported without applying it, so the size of the change is
    knowable before it is made."""
    db_path = _setup(home_dir)
    _v1_row(db_path, "s-old")

    result = CliRunner().invoke(cli, ["metrics", "backfill-host", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "1" in result.output

    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(db_path)
    rows = db.query_stats(period="all")
    db.close()
    assert rows[0]["host"] == ""


def test_metrics_backfill_host_reports_when_there_is_nothing_to_do(home_dir: Path) -> None:
    _setup(home_dir)

    result = CliRunner().invoke(cli, ["metrics", "backfill-host"])

    assert result.exit_code == 0, result.output
    assert "0" in result.output
