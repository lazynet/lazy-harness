"""Integration tests for lh knowledge commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import Config, HarnessConfig, KnowledgeConfig, save_config


def _setup_config(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    knowledge_dir = home_dir / "knowledge"
    knowledge_dir.mkdir()
    cfg = Config(
        harness=HarnessConfig(version="1"), knowledge=KnowledgeConfig(path=str(knowledge_dir))
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
