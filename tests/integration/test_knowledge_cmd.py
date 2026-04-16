"""Integration tests for lh knowledge commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import Config, HarnessConfig, KnowledgeConfig, save_config


def _setup_config(home_dir: Path, compound_loop_enabled: bool = False) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    knowledge_dir = home_dir / "knowledge"
    knowledge_dir.mkdir()
    from lazy_harness.core.config import CompoundLoopConfig

    cfg = Config(
        harness=HarnessConfig(version="1"),
        knowledge=KnowledgeConfig(path=str(knowledge_dir)),
        compound_loop=CompoundLoopConfig(enabled=compound_loop_enabled),
    )
    save_config(cfg, config_path)
    return config_path


def test_knowledge_status(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["knowledge", "status"])
    assert result.exit_code == 0
    assert "knowledge" in result.output.lower()


def _write_session_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_knowledge_export_session_force(home_dir: Path) -> None:
    _setup_config(home_dir)
    session_file = home_dir / "sessions" / "c94df89e-2b8c-424b-a9dd-7a534d210989.jsonl"
    # Deliberately non-interactive: no permission-mode / last-prompt records.
    _write_session_jsonl(
        session_file,
        [
            {"type": "system", "cwd": "/tmp/proj", "timestamp": "2026-04-15T17:00:00"},
            {"type": "user", "message": {"content": "q1"}, "timestamp": "2026-04-15T17:00:01"},
            {"type": "assistant", "message": {"content": "a1"}, "timestamp": "2026-04-15T17:00:02"},
            {"type": "user", "message": {"content": "q2"}, "timestamp": "2026-04-15T17:00:03"},
            {"type": "assistant", "message": {"content": "a2"}, "timestamp": "2026-04-15T17:00:04"},
        ],
    )
    runner = CliRunner()

    # Without --force: skipped and reports reason.
    result = runner.invoke(cli, ["knowledge", "export-session", str(session_file)])
    assert result.exit_code == 0, result.output
    assert "non-interactive" in result.output

    # With --force: exported.
    result = runner.invoke(cli, ["knowledge", "export-session", str(session_file), "--force"])
    assert result.exit_code == 0, result.output
    assert "exported" in result.output.lower()
    # Exported file lives under knowledge_dir/sessions/YYYY-MM/.
    exported = list((home_dir / "knowledge" / "sessions").rglob("*.md"))
    assert len(exported) == 1
    assert "c94df89e" in exported[0].name


def test_knowledge_handoff_now_errors_when_compound_loop_disabled(
    home_dir: Path, monkeypatch, tmp_path: Path
) -> None:
    _setup_config(home_dir, compound_loop_enabled=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    runner = CliRunner()
    result = runner.invoke(cli, ["knowledge", "handoff-now"])
    assert result.exit_code != 0
    assert "compound_loop" in result.output.lower()


def test_knowledge_handoff_now_enqueues_task_force(
    home_dir: Path, monkeypatch, tmp_path: Path
) -> None:
    from lazy_harness.knowledge import compound_loop as cl_lib

    # _config_to_dict doesn't round-trip compound_loop, so inline a TOML that
    # `load_config` will parse back with enabled=True.
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
[harness]
version = "1"

[agent]
type = "claude-code"

[compound_loop]
enabled = true
"""
    )

    claude_dir = tmp_path / "claude"
    cwd = tmp_path / "proj"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = claude_dir / "projects" / encoded
    sessions_dir.mkdir(parents=True)
    session_jsonl = sessions_dir / "deadbeef-feed-cafe-babe-1234abcd0001.jsonl"
    _write_session_jsonl(
        session_jsonl,
        [
            {"type": "permission-mode"},
            {"type": "user", "message": {"content": "x" * 250}},
            {"type": "assistant", "message": {"content": "ok"}},
        ],
    )

    queue_dir = claude_dir / "queue"
    # Pretend a Stop hook just queued a task — debounce would block a normal run.
    import time as _t

    prior_task = cl_lib.create_task(
        queue_dir,
        cwd,
        session_jsonl,
        "deadbeef-feed-cafe-babe-1234abcd0001",
        sessions_dir / "memory",
    )
    prior_task.rename(queue_dir / f"{int(_t.time()) - 5}-deadbee.task")

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))
    monkeypatch.chdir(cwd)
    from lazy_harness.cli import knowledge_cmd as knowledge_mod

    monkeypatch.setattr(knowledge_mod.subprocess, "Popen", lambda *a, **kw: None)

    runner = CliRunner()
    result = runner.invoke(cli, ["knowledge", "handoff-now"])

    assert result.exit_code == 0, result.output
    assert "queued" in result.output.lower()
    assert len(list(queue_dir.glob("*.task"))) == 2


def test_knowledge_export_session_missing_file(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["knowledge", "export-session", str(home_dir / "nope.jsonl")])
    assert result.exit_code != 0
    assert "does not exist" in result.output.lower()


def test_knowledge_no_path(home_dir: Path) -> None:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(harness=HarnessConfig(version="1"))
    save_config(cfg, config_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["knowledge", "status"])
    assert "not configured" in result.output.lower() or result.exit_code != 0
