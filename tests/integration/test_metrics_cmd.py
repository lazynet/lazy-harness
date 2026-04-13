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
