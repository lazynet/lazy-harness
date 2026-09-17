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


# --- a Codex profile, metered end to end (ADR-053) --------------------------


def _codex_rollout(profile_dir: Path, uuid: str, *, model: str = "gpt-5-codex") -> None:
    """Synthetic, rebuilt from `specs/designs/codex-evidence.md` §5."""
    d = profile_dir / "sessions" / "2026" / "09" / "16"
    d.mkdir(parents=True, exist_ok=True)
    entries = [
        {
            "timestamp": "2026-09-16T12:02:13.926Z",
            "type": "session_meta",
            "payload": {"id": uuid, "session_id": uuid, "cwd": "/w/demo", "cli_version": "0.154.0"},
            "ordinal": 0,
        },
        {
            "timestamp": "2026-09-16T12:02:13.926Z",
            "type": "turn_context",
            "payload": {"cwd": "/w/demo", "model": model, "turn_id": "t1"},
            "ordinal": 1,
        },
        {
            "timestamp": "2026-09-16T12:02:14.926Z",
            "type": "token_usage_record",
            "payload": {
                "session_id": uuid,
                "turn_id": "t1",
                "response_id": f"{uuid}-r1",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cached_input_tokens": 0,
                    "cache_write_input_tokens": 0,
                },
            },
            "ordinal": 2,
        },
    ]
    (d / f"rollout-2026-09-16T09-02-04-{uuid}.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in entries)
    )


def _setup_codex(home_dir: Path, *, billing_model: str = "per_token") -> tuple[Path, Path]:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    db_path = home_dir / ".local" / "share" / "lazy-harness" / "metrics.db"
    profile_dir = home_dir / ".codex-lazy"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="cx",
            items={
                "cx": ProfileEntry(
                    config_dir=str(profile_dir),
                    roots=["~"],
                    agent="codex",
                    billing_model=billing_model,
                )
            },
        ),
        monitoring=MonitoringConfig(
            enabled=True,
            db=str(db_path),
            # A rate for the model under test, on purpose: without one, a
            # `per_token` row also prices to 0.0 and the `flat_rate`
            # assertions below would hold for the wrong reason.
            pricing={"gpt-5-codex": {"input": 1.25, "output": 10.0}},
        ),
    )
    save_config(cfg, config_path)
    profile_dir.mkdir(parents=True, exist_ok=True)
    return db_path, config_path


def test_metrics_ingest_meters_a_codex_profile(home_dir: Path) -> None:
    """The iteration's success criterion, through the CLI the user runs."""
    db_path, _ = _setup_codex(home_dir)
    uuid = "01a0aa69-fce1-7930-a795-dc39a8c1ebb4"
    _codex_rollout(home_dir / ".codex-lazy", uuid)

    result = CliRunner().invoke(cli, ["metrics", "ingest"])
    assert result.exit_code == 0, result.output

    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(db_path)
    rows = db.query_stats(period="all")
    db.close()

    assert len(rows) == 1
    assert rows[0]["session"] == uuid
    assert rows[0]["agent"] == "codex"
    assert rows[0]["model"] == "gpt-5-codex"
    assert rows[0]["project"] == "demo"
    assert (rows[0]["input"], rows[0]["output"]) == (100, 50)


def test_a_per_token_codex_profile_is_priced_from_the_table(home_dir: Path) -> None:
    """The control for the test below: the same rollout, billed per token, costs money."""
    db_path, _ = _setup_codex(home_dir, billing_model="per_token")
    _codex_rollout(home_dir / ".codex-lazy", "01a0aa69-fce1-7930-a795-dc39a8c1ebb4")

    assert CliRunner().invoke(cli, ["metrics", "ingest"]).exit_code == 0

    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(db_path)
    rows = db.query_stats(period="all")
    db.close()

    assert rows[0]["billing_model"] == "per_token"
    assert rows[0]["cost"] > 0


def test_a_flat_rate_codex_profile_costs_nothing(home_dir: Path) -> None:
    """ADR-050: the subscription already paid for the usage, so the row is $0.

    The model *has* a rate here — see `_setup_codex` — so this asserts the
    billing model short-circuited pricing, and not merely that an unpriced
    model priced to nothing.
    """
    db_path, _ = _setup_codex(home_dir, billing_model="flat_rate")
    _codex_rollout(home_dir / ".codex-lazy", "01a0aa69-fce1-7930-a795-dc39a8c1ebb5")

    result = CliRunner().invoke(cli, ["metrics", "ingest"])
    assert result.exit_code == 0, result.output

    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(db_path)
    rows = db.query_stats(period="all")
    db.close()

    assert rows[0]["cost"] == 0.0
    assert rows[0]["billing_model"] == "flat_rate"


def test_an_unpriced_model_on_a_flat_rate_profile_is_not_a_pricing_gap(
    home_dir: Path,
) -> None:
    """Real spend that is not per-token metered, so an absent rate is not a gap."""
    _setup_codex(home_dir, billing_model="flat_rate")
    _codex_rollout(home_dir / ".codex-lazy", "01a0aa69-fce1-7930-a795-dc39a8c1ebb6", model="o9")

    result = CliRunner().invoke(cli, ["metrics", "ingest"])
    assert result.exit_code == 0, result.output
    assert "o9" not in result.output


def test_ingesting_a_codex_profile_twice_stores_the_same_totals(home_dir: Path) -> None:
    """Round trip: the row survives being written, read, written and read again.

    Not idempotence for its own sake — `upsert_stats` overwrites on
    `(session, model)`, so a second run that read the model differently, or
    identified the session differently, would silently create a second row
    rather than update the first.
    """
    db_path, _ = _setup_codex(home_dir)
    _codex_rollout(home_dir / ".codex-lazy", "01a0aa69-fce1-7930-a795-dc39a8c1ebb7")

    from lazy_harness.monitoring.db import MetricsDB

    def _rows() -> list[dict]:
        db = MetricsDB(db_path)
        try:
            return [dict(r) for r in db.query_stats(period="all")]
        finally:
            db.close()

    assert CliRunner().invoke(cli, ["metrics", "ingest"]).exit_code == 0
    first = _rows()
    assert CliRunner().invoke(cli, ["metrics", "ingest"]).exit_code == 0
    second = _rows()

    assert len(first) == 1
    assert first == second


def test_a_codex_profile_survives_a_config_round_trip(home_dir: Path) -> None:
    """save, load, save, load — the agent and the billing model must both persist."""
    from lazy_harness.core.config import load_config

    _, config_path = _setup_codex(home_dir, billing_model="flat_rate")

    once = load_config(config_path)
    save_config(once, config_path)
    twice = load_config(config_path)

    for cfg in (once, twice):
        entry = cfg.profiles.items["cx"]
        assert entry.agent == "codex"
        assert entry.billing_model == "flat_rate"
