"""Integration tests for lh status commands."""

from __future__ import annotations

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


def _setup_config(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    db_path = home_dir / ".local" / "share" / "lazy-harness" / "metrics.db"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(config_dir=str(home_dir / ".claude-personal"), roots=["~"])
            },
        ),
        monitoring=MonitoringConfig(enabled=True, db=str(db_path)),
    )
    save_config(cfg, config_path)
    (home_dir / ".claude-personal").mkdir(parents=True, exist_ok=True)
    return config_path


def test_status_overview(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0


def test_status_costs(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "costs"])
    assert result.exit_code == 0


def test_status_no_monitoring(home_dir: Path) -> None:
    """When monitoring is disabled, overview still renders but token stats are empty."""
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        monitoring=MonitoringConfig(enabled=False),
    )
    save_config(cfg, config_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    # Overview always renders the panel header
    assert "lh status" in result.output
    # Token line shows zeros because monitoring is off
    assert "0 in" in result.output


def _seed_pre_adr037_db(home_dir: Path) -> Path:
    """A metrics DB written before ADR-037: no host, no workload column."""
    import sqlite3

    db_path = home_dir / ".local" / "share" / "lazy-harness" / "metrics.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE session_stats (
            session TEXT NOT NULL,
            date TEXT NOT NULL,
            model TEXT NOT NULL,
            profile TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read INTEGER NOT NULL DEFAULT 0,
            cache_create INTEGER NOT NULL DEFAULT 0,
            cost REAL NOT NULL DEFAULT 0.0,
            user_id TEXT NOT NULL DEFAULT 'local',
            tenant_id TEXT NOT NULL DEFAULT 'local',
            event_id TEXT NOT NULL DEFAULT '',
            UNIQUE(session, model)
        )
        """
    )
    conn.execute(
        "INSERT INTO session_stats (session, date, model, project, cost) VALUES (?,?,?,?,?)",
        ("legacy-session", "2026-08-31", "claude-opus-5", "lazy-harness", 4.25),
    )
    conn.commit()
    conn.close()
    return db_path


def test_status_tokens_renders_a_pre_adr037_row(home_dir: Path) -> None:
    """ADR-037: v1 rows already in the store must keep rendering."""
    _setup_config(home_dir)
    _seed_pre_adr037_db(home_dir)

    result = CliRunner().invoke(cli, ["status", "tokens", "--period", "all", "--json"])

    assert result.exit_code == 0
    assert "4.25" in result.stdout


def test_status_tokens_groups_a_pre_adr037_row_under_unknown_host(home_dir: Path) -> None:
    """The migration backfills nothing, so the dimension reads as unknown."""
    _setup_config(home_dir)
    _seed_pre_adr037_db(home_dir)

    result = CliRunner().invoke(
        cli, ["status", "tokens", "--period", "all", "--by", "host", "--json"]
    )

    assert result.exit_code == 0
    assert "unknown" in result.stdout


def test_status_tokens_groups_by_workload(home_dir: Path) -> None:
    _setup_config(home_dir)
    from lazy_harness.monitoring.db import MetricsDB

    db_path = home_dir / ".local" / "share" / "lazy-harness" / "metrics.db"
    db = MetricsDB(db_path)
    try:
        db.upsert_stats(
            [
                {
                    "session": "s1",
                    "date": "2026-08-31",
                    "model": "claude-opus-5",
                    "project": "p",
                    "cost": 1.0,
                }
            ]
        )
        db._conn.execute("UPDATE session_stats SET workload = 'vault-pass'")
        db._conn.commit()
    finally:
        db.close()

    result = CliRunner().invoke(
        cli, ["status", "tokens", "--period", "all", "--by", "workload", "--json"]
    )

    assert result.exit_code == 0
    assert "vault-pass" in result.stdout


def test_status_tokens_filters_by_workload(home_dir: Path) -> None:
    """FILTERABLE names host and workload, so the CLI must expose them."""
    _setup_config(home_dir)
    from lazy_harness.monitoring.db import MetricsDB

    db_path = home_dir / ".local" / "share" / "lazy-harness" / "metrics.db"
    db = MetricsDB(db_path)
    try:
        db.upsert_stats(
            [
                {"session": "a", "date": "2026-08-31", "model": "m", "project": "p", "cost": 1.0},
                {"session": "b", "date": "2026-08-31", "model": "m", "project": "p", "cost": 9.0},
            ]
        )
        db._conn.execute("UPDATE session_stats SET workload='vault-pass' WHERE session='a'")
        db._conn.execute("UPDATE session_stats SET workload='other' WHERE session='b'")
        db._conn.commit()
    finally:
        db.close()

    result = CliRunner().invoke(
        cli,
        ["status", "tokens", "--period", "all", "--workload", "vault", "--json"],
    )

    assert result.exit_code == 0
    assert "9.0" not in result.stdout


def test_status_tokens_filters_by_host(home_dir: Path) -> None:
    _setup_config(home_dir)
    from lazy_harness.monitoring.db import MetricsDB

    db_path = home_dir / ".local" / "share" / "lazy-harness" / "metrics.db"
    db = MetricsDB(db_path)
    try:
        db.upsert_stats(
            [
                {"session": "a", "date": "2026-08-31", "model": "m", "project": "p", "cost": 1.0},
                {"session": "b", "date": "2026-08-31", "model": "m", "project": "p", "cost": 9.0},
            ]
        )
        db._conn.execute("UPDATE session_stats SET host='agents' WHERE session='a'")
        db._conn.execute("UPDATE session_stats SET host='LazyMBP' WHERE session='b'")
        db._conn.commit()
    finally:
        db.close()

    result = CliRunner().invoke(
        cli, ["status", "tokens", "--period", "all", "--host", "agents", "--json"]
    )

    assert result.exit_code == 0
    assert "9.0" not in result.stdout
