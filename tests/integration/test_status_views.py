"""Integration tests for `lh status` subcommand views.

These tests exercise each view through the CLI runner with realistic fixture
data: profile dirs, session JSONLs, hooks logs, queue files, memory JSONLs.
The intent is to catch rendering bugs, missing-data crashes, and regressions
in cross-view contracts.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
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


def _setup(home_dir: Path, with_profile_data: bool = False) -> Path:
    """Write a config with one profile + optional fixture dirs/files.

    Returns the profile config dir path.
    """
    profile_dir = home_dir / ".claude-personal"
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(
                    config_dir=str(profile_dir),
                    roots=[str(home_dir / "repos")],
                ),
            },
        ),
        monitoring=MonitoringConfig(
            enabled=True,
            db=str(home_dir / ".local/share/lazy-harness/metrics.db"),
        ),
    )
    save_config(cfg, config_path)
    if with_profile_data:
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "x"}]}],
                    },
                    "mcpServers": {"foo": {}},
                }
            )
        )
    return profile_dir


def test_status_profiles_view(home_dir: Path) -> None:
    _setup(home_dir, with_profile_data=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "profiles"])
    assert result.exit_code == 0, result.output
    assert "personal" in result.output
    assert "configured" in result.output


def test_status_profiles_handles_missing_profile_dir(home_dir: Path) -> None:
    _setup(home_dir, with_profile_data=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "profiles"])
    assert result.exit_code == 0
    assert "missing" in result.output


def test_status_projects_with_session_jsonl(home_dir: Path) -> None:
    profile = _setup(home_dir, with_profile_data=True)
    project_dir = profile / "projects" / "-Users-x-repos-lazy-foo"
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "session1.jsonl"
    jsonl.write_text(
        json.dumps({"type": "system", "gitBranch": "main", "timestamp": "2026-04-01T10:00:00Z"})
        + "\n"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "projects"])
    assert result.exit_code == 0, result.output
    # Either decoded or fallback; we just assert the row was rendered
    assert "personal" in result.output


def test_status_projects_empty(home_dir: Path) -> None:
    _setup(home_dir, with_profile_data=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "projects"])
    assert result.exit_code == 0
    assert "No projects" in result.output


def test_status_hooks_renders_log_entries(home_dir: Path) -> None:
    profile = _setup(home_dir, with_profile_data=True)
    logs_dir = profile / "logs"
    logs_dir.mkdir(parents=True)
    today = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    (logs_dir / "hooks.log").write_text(
        f"{today} session-export: fired cwd=/Users/x/repos/lazy/foo\n"
        f"{today} compound-loop: fired cwd=/Users/x/repos/lazy/foo\n"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "hooks"])
    assert result.exit_code == 0, result.output
    assert "session-export" in result.output
    assert "compound-loop" in result.output


def test_status_queue_counts_pending_and_done(home_dir: Path) -> None:
    profile = _setup(home_dir, with_profile_data=True)
    queue_dir = profile / "queue"
    done_dir = queue_dir / "done"
    done_dir.mkdir(parents=True)
    (queue_dir / "1234-abc.task").write_text("session_id=abc\n")
    (done_dir / "1233-old.task").write_text("session_id=old\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "queue"])
    assert result.exit_code == 0, result.output
    assert "Pending:    1" in result.output
    assert "Done total: 1" in result.output


def test_status_memory_aggregates_jsonl(home_dir: Path) -> None:
    profile = _setup(home_dir, with_profile_data=True)
    project_dir = profile / "projects" / "-Users-x-repos-lazy-foo"
    memory_dir = project_dir / "memory"
    memory_dir.mkdir(parents=True)
    today = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    (memory_dir / "decisions.jsonl").write_text(
        json.dumps({"ts": today, "summary": "chose pattern X"}) + "\n"
        + json.dumps({"ts": today, "summary": "chose pattern Y"}) + "\n"
    )
    (memory_dir / "failures.jsonl").write_text(
        json.dumps({"ts": today, "summary": "broke build"}) + "\n"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "memory"])
    assert result.exit_code == 0, result.output
    # Counts
    assert "2" in result.output  # decisions
    assert "1" in result.output  # failures
    # Recent sections
    assert "Recent decisions" in result.output
    assert "Recent failures" in result.output


def test_status_memory_empty(home_dir: Path) -> None:
    _setup(home_dir, with_profile_data=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "memory"])
    assert result.exit_code == 0
    assert "No project memory" in result.output


def test_status_sessions_no_db(home_dir: Path) -> None:
    _setup(home_dir, with_profile_data=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "sessions"])
    assert result.exit_code == 0
    assert "DB not available" in result.output or "No data" in result.output


def test_status_tokens_no_db(home_dir: Path) -> None:
    _setup(home_dir, with_profile_data=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "tokens", "--by", "model"])
    assert result.exit_code == 0
    assert "DB not available" in result.output or "No data" in result.output


def test_status_overview_runs_without_db(home_dir: Path) -> None:
    _setup(home_dir, with_profile_data=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0, result.output
    assert "lh status" in result.output
    assert "Profiles" in result.output


def test_status_cron_no_managed_jobs(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(home_dir, with_profile_data=True)
    fake_la = home_dir / "Library" / "LaunchAgents"
    fake_la.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "cron"])
    assert result.exit_code == 0
    assert "No managed jobs" in result.output
