"""Test that ingest_all fans out to every configured sink."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import (
    Config,
    MetricsConfig,
    ProfileEntry,
    ProfilesConfig,
    SinkDefinition,
)
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.ingest import ingest_all
from lazy_harness.plugins.contracts import (
    DrainResult,
    MetricEvent,
    SinkHealth,
    SinkWriteResult,
)


class _CountingSink:
    name = "counting"

    def __init__(self) -> None:
        self.events: list[MetricEvent] = []

    def write(self, event: MetricEvent) -> SinkWriteResult:
        self.events.append(event)
        return SinkWriteResult.ok()

    def drain(self, batch_size: int) -> DrainResult:
        return DrainResult(sent=0, failed=0, remaining=0)

    def health(self) -> SinkHealth:
        return SinkHealth(reachable=True)


def _write_fake_jsonl(projects_dir: Path, session_id: str) -> None:
    """Drop a minimal Claude Code session JSONL the ingest pipeline can parse."""
    proj = projects_dir / "-Users-martin-repos-lazy-lazy-harness"
    proj.mkdir(parents=True, exist_ok=True)
    f = proj / f"{session_id}.jsonl"
    f.write_text(
        '{"type":"assistant","message":{"id":"msg1","model":"claude-sonnet-4-5",'
        '"usage":{"input_tokens":100,"output_tokens":50,'
        '"cache_read_input_tokens":0,"cache_creation_input_tokens":0}},'
        '"timestamp":"2026-04-14T10:00:00Z"}\n'
    )


def test_ingest_fans_out_to_every_configured_sink(tmp_path: Path) -> None:
    profile_dir = tmp_path / "claude-personal"
    _write_fake_jsonl(profile_dir / "projects", "sess1")

    cfg = Config()
    cfg.profiles = ProfilesConfig(
        default="personal",
        items={
            "personal": ProfileEntry(
                config_dir=str(profile_dir), roots=[], lazynorth_doc=""
            ),
        },
    )
    cfg.metrics = MetricsConfig(
        sinks=["sqlite_local", "counting"],
        sink_configs={
            "sqlite_local": SinkDefinition(options={}),
            "counting": SinkDefinition(options={}),
        },
    )

    db = MetricsDB(tmp_path / "m.db")
    counting = _CountingSink()
    try:
        ingest_all(cfg, db, pricing={}, sinks=[counting])
        assert len(counting.events) == 1
        ev = counting.events[0]
        assert ev.session == "sess1"
        assert ev.profile == "personal"
        assert ev.user_id  # stamped by identity resolver
    finally:
        db.close()


def _one_profile_config(profile_dir: Path) -> Config:
    cfg = Config()
    cfg.profiles = ProfilesConfig(
        default="personal",
        items={
            "personal": ProfileEntry(config_dir=str(profile_dir), roots=[], lazynorth_doc=""),
        },
    )
    cfg.metrics = MetricsConfig(
        sinks=["sqlite_local"],
        sink_configs={"sqlite_local": SinkDefinition(options={})},
    )
    return cfg


def test_ingest_stamps_the_host_on_every_event(tmp_path: Path) -> None:
    """ADR-037 D3: the ingesting process runs on the machine that wrote the
    transcripts, so `host` needs no channel — it is resolved here."""
    from lazy_harness.core.identity import resolve_host

    profile_dir = tmp_path / "claude-personal"
    _write_fake_jsonl(profile_dir / "projects", "sess1")

    db = MetricsDB(tmp_path / "m.db")
    counting = _CountingSink()
    try:
        ingest_all(_one_profile_config(profile_dir), db, pricing={}, sinks=[counting])
    finally:
        db.close()

    assert counting.events[0].host == resolve_host()
    assert counting.events[0].host != ""


def test_ingest_joins_the_workload_recorded_by_lh_exec(tmp_path: Path) -> None:
    profile_dir = tmp_path / "claude-personal"
    _write_fake_jsonl(profile_dir / "projects", "sess1")

    db = MetricsDB(tmp_path / "m.db")
    counting = _CountingSink()
    try:
        db.set_attribution(session="sess1", workload="vault-pass", host="agents")
        ingest_all(_one_profile_config(profile_dir), db, pricing={}, sinks=[counting])
    finally:
        db.close()

    assert counting.events[0].workload == "vault-pass"


def test_ingest_leaves_workload_empty_for_an_unattributed_session(tmp_path: Path) -> None:
    """Interactive sessions have no caller label, and that is correct."""
    profile_dir = tmp_path / "claude-personal"
    _write_fake_jsonl(profile_dir / "projects", "sess1")

    db = MetricsDB(tmp_path / "m.db")
    counting = _CountingSink()
    try:
        db.set_attribution(session="a-different-session", workload="vault-pass")
        ingest_all(_one_profile_config(profile_dir), db, pricing={}, sinks=[counting])
    finally:
        db.close()

    assert counting.events[0].workload == ""


def test_ingest_does_not_fold_host_into_user_id(tmp_path: Path) -> None:
    """ADR-037 D2: `user_id` keeps identifying the person, not the machine."""
    profile_dir = tmp_path / "claude-personal"
    _write_fake_jsonl(profile_dir / "projects", "sess1")

    cfg = _one_profile_config(profile_dir)
    cfg.metrics.user_id = "martin"

    db = MetricsDB(tmp_path / "m.db")
    counting = _CountingSink()
    try:
        ingest_all(cfg, db, pricing={}, sinks=[counting])
    finally:
        db.close()

    assert counting.events[0].user_id == "martin"
    assert counting.events[0].host != "martin"


def test_ingest_event_id_is_unchanged_by_the_new_dimensions(tmp_path: Path) -> None:
    """ADR-037 D6: the remote upserts by event_id; new inputs would re-land
    every historical event as a new row and double the recorded cost."""
    from lazy_harness.monitoring.event_id import derive_event_id

    profile_dir = tmp_path / "claude-personal"
    _write_fake_jsonl(profile_dir / "projects", "sess1")

    db = MetricsDB(tmp_path / "m.db")
    counting = _CountingSink()
    try:
        db.set_attribution(session="sess1", workload="vault-pass")
        ingest_all(_one_profile_config(profile_dir), db, pricing={}, sinks=[counting])
    finally:
        db.close()

    ev = counting.events[0]
    assert ev.event_id == derive_event_id(
        profile="personal", session="sess1", model="claude-sonnet-4-5"
    )
