"""ADR-037 verification: the workload channel, end to end.

These are the checks the ADR names. They exercise the real `lh exec`, a real
child process, a real transcript on disk and the real ingest, because an
artifact is verified by the system that consumes it and not by the test that
wrote it.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

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

# Writes a transcript under the session id it was told to use, exactly where
# the ingest looks for one, then reports that id back in its envelope.
TRANSCRIBING_AGENT = """
    import json, os, pathlib, sys
    sys.stdin.read()
    argv = sys.argv[1:]
    sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else "unpinned"
    proj = pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "testproj"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / (sid + ".jsonl")).write_text(json.dumps({
        "type": "assistant",
        "timestamp": "2026-08-31T10:00:00Z",
        "message": {"id": "msg-" + sid, "model": "claude-haiku-4-5",
                    "usage": {"input_tokens": 10, "output_tokens": 5,
                              "cache_read_input_tokens": 0,
                              "cache_creation_input_tokens": 0}},
    }) + "\\n")
    print(json.dumps({"is_error": False, "result": "ok", "session_id": sid}))
"""

# Writes its transcript and then hangs, so `lh exec` has to kill it.
HANGING_AGENT = """
    import json, os, pathlib, sys, time
    sys.stdin.read()
    argv = sys.argv[1:]
    sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else "unpinned"
    proj = pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "testproj"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / (sid + ".jsonl")).write_text(json.dumps({
        "type": "assistant",
        "timestamp": "2026-08-31T10:00:00Z",
        "message": {"id": "msg-" + sid, "model": "claude-haiku-4-5",
                    "usage": {"input_tokens": 10, "output_tokens": 5,
                              "cache_read_input_tokens": 0,
                              "cache_creation_input_tokens": 0}},
    }) + "\\n")
    sys.stdout.flush()
    time.sleep(120)
"""


class _CapturingSink:
    name = "capturing"

    def __init__(self) -> None:
        self.events: list[MetricEvent] = []

    def write(self, event: MetricEvent) -> SinkWriteResult:
        self.events.append(event)
        return SinkWriteResult.ok()

    def drain(self, batch_size: int) -> DrainResult:
        return DrainResult(sent=0, failed=0, remaining=0)

    def health(self) -> SinkHealth:
        return SinkHealth(reachable=True)


def _write_agent(body: str) -> Path:
    versions = Path.home() / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    binary = versions / "0.0.1-fake"
    binary.write_text(f"#!{sys.executable}\n{textwrap.dedent(body)}")
    binary.chmod(0o755)
    return binary


@pytest.fixture
def channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A one-profile harness whose metrics DB `lh exec` and the ingest share."""
    lh_config = tmp_path / "lh"
    lh_config.mkdir()
    profile_dir = tmp_path / "cfg-personal"
    (lh_config / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        '[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "personal"\n\n'
        f'[profiles.personal]\nconfig_dir = "{profile_dir}"\nroots = []\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setenv("LH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    return {"profile_dir": profile_dir, "db": tmp_path / "data" / "metrics.db"}


def _cfg(profile_dir: Path) -> Config:
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


def _exec(args: list[str]) -> tuple[int, dict]:
    from lazy_harness.cli.exec_cmd import exec_cmd

    result = CliRunner().invoke(exec_cmd, args, input="hello")
    try:
        return result.exit_code, json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.exit_code, {}


def test_the_workload_reaches_the_ingested_event(channel: dict[str, Path]) -> None:
    """One session id ties `lh exec`, the transcript on disk and the event."""
    _write_agent(TRANSCRIBING_AGENT)

    code, envelope = _exec(["--workload", "vault-pass"])
    assert code == 0
    pinned = envelope["raw"]["session_id"]

    transcript = channel["profile_dir"] / "projects" / "testproj" / f"{pinned}.jsonl"
    assert transcript.is_file(), "the agent wrote its transcript under the pinned id"

    db = MetricsDB(channel["db"])
    sink = _CapturingSink()
    try:
        assert db.attribution_map() == {pinned: "vault-pass"}
        ingest_all(_cfg(channel["profile_dir"]), db, pricing={}, sinks=[sink])
    finally:
        db.close()

    assert len(sink.events) == 1
    assert sink.events[0].session == pinned
    assert sink.events[0].workload == "vault-pass"


def test_attribution_survives_the_timeout(channel: dict[str, Path]) -> None:
    """The most expensive outcome `lh exec` has, and the reason the write is
    pre-spawn: the kill must not outrun the attribution row.

    The envelope now bills the killed run from its transcript too, but only the
    ingest puts that cost in the store `lh status --by workload` reads, so the
    row is still what makes the run answerable by caller."""
    _write_agent(HANGING_AGENT)

    code, envelope = _exec(["--workload", "vault-pass", "--timeout", "2"])

    assert code == 124
    assert envelope["error"]["kind"] == "timeout"
    assert envelope["cost_usd"] is not None, "a killed run is billed from its transcript"
    assert envelope["cost_source"] == "transcript"

    db = MetricsDB(channel["db"])
    sink = _CapturingSink()
    try:
        recorded = db.attribution_map()
        assert list(recorded.values()) == ["vault-pass"]
        ingest_all(_cfg(channel["profile_dir"]), db, pricing={}, sinks=[sink])
    finally:
        db.close()

    assert len(sink.events) == 1, "the ingest is what makes the run queryable by caller"
    assert sink.events[0].workload == "vault-pass"


def test_an_orphan_attribution_row_is_tolerated(channel: dict[str, Path]) -> None:
    """A run killed before its first turn leaves a row no session joins."""
    _write_agent(TRANSCRIBING_AGENT)
    _exec(["--workload", "vault-pass"])

    db = MetricsDB(channel["db"])
    sink = _CapturingSink()
    try:
        db.set_attribution(session="never-produced-a-transcript", workload="dead-run")
        report = ingest_all(_cfg(channel["profile_dir"]), db, pricing={}, sinks=[sink])
    finally:
        db.close()

    assert report.errors == []
    assert "dead-run" not in [e.workload for e in sink.events]


def test_local_columns_stay_empty_when_sqlite_local_is_disabled(
    channel: dict[str, Path],
) -> None:
    """Two writers, one row: `upsert_stats` writes no dimensions and only the
    `sqlite_local` sink calls `upsert_event`. With it off, the remote sink still
    receives host and workload while the local table does not."""
    _write_agent(TRANSCRIBING_AGENT)
    _exec(["--workload", "vault-pass"])

    cfg = _cfg(channel["profile_dir"])
    cfg.metrics = MetricsConfig(sinks=["capturing"], sink_configs={})

    db = MetricsDB(channel["db"])
    sink = _CapturingSink()
    try:
        ingest_all(cfg, db, pricing={}, sinks=[sink])
        rows = db.query_stats()
    finally:
        db.close()

    assert sink.events[0].workload == "vault-pass"
    assert sink.events[0].host != ""
    assert rows[0]["workload"] == "", "no sqlite_local sink, no local dimensions"
    assert rows[0]["host"] == ""


def test_the_session_id_is_never_taken_from_the_environment(
    channel: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`LH_WORKLOAD` is a channel; the session id is not. A remembered id is
    refused by the real agent with exit 1 and an empty stdout."""
    _write_agent(TRANSCRIBING_AGENT)
    monkeypatch.setenv("LH_SESSION_ID", "a-remembered-id")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "a-remembered-id")

    _, envelope = _exec(["--workload", "vault-pass"])

    assert envelope["raw"]["session_id"] != "a-remembered-id"
