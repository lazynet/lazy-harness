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
