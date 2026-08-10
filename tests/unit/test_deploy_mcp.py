"""Tests for deploy_mcp_servers — MCP block writer in deploy/engine.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_cfg(profile_dir: Path, agent_type: str = "claude-code"):
    from lazy_harness.core.config import Config, ProfileEntry

    cfg = Config()
    cfg.agent.type = agent_type
    cfg.profiles.items = {"default": ProfileEntry(config_dir=str(profile_dir))}
    return cfg


def test_deploy_mcp_servers_writes_claude_json_when_qmd_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / ".claude-test"
    profile_dir.mkdir()

    monkeypatch.setattr(
        engine,
        "_collect_mcp_servers",
        lambda cfg: {"qmd": {"command": "qmd", "args": ["mcp"]}},
    )

    cfg = _make_cfg(profile_dir)
    engine.deploy_mcp_servers(cfg)

    claude_json = json.loads((profile_dir / ".claude.json").read_text())
    assert "mcpServers" in claude_json
    assert claude_json["mcpServers"]["qmd"]["command"] == "qmd"


def test_deploy_mcp_servers_does_not_write_mcp_block_to_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / ".claude-test"
    profile_dir.mkdir()

    monkeypatch.setattr(
        engine,
        "_collect_mcp_servers",
        lambda cfg: {"qmd": {"command": "qmd", "args": ["mcp"]}},
    )

    engine.deploy_mcp_servers(_make_cfg(profile_dir))

    settings_file = profile_dir / "settings.json"
    if settings_file.is_file():
        settings = json.loads(settings_file.read_text())
        assert "mcpServers" not in settings


def test_deploy_mcp_servers_preserves_existing_claude_json_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / ".claude-test"
    profile_dir.mkdir()
    (profile_dir / ".claude.json").write_text(
        json.dumps(
            {
                "projects": {"/some/path": {"history": []}},
                "userID": "abc123",
                "mcpServers": {"backlog": {"command": "backlog", "args": ["mcp", "start"]}},
            }
        )
    )

    monkeypatch.setattr(
        engine,
        "_collect_mcp_servers",
        lambda cfg: {"qmd": {"command": "qmd", "args": ["mcp"]}},
    )

    engine.deploy_mcp_servers(_make_cfg(profile_dir))

    claude_json = json.loads((profile_dir / ".claude.json").read_text())
    assert claude_json["projects"] == {"/some/path": {"history": []}}
    assert claude_json["userID"] == "abc123"
    assert "qmd" in claude_json["mcpServers"]
    assert "backlog" in claude_json["mcpServers"]


def test_deploy_mcp_servers_noop_when_no_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / ".claude-test"
    profile_dir.mkdir()
    monkeypatch.setattr(engine, "_collect_mcp_servers", lambda cfg: {})

    engine.deploy_mcp_servers(_make_cfg(profile_dir))

    assert not (profile_dir / ".claude.json").is_file()
    assert not (profile_dir / "settings.json").is_file()


def test_collect_mcp_servers_includes_qmd_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: True)
    result = engine._collect_mcp_servers(Config())
    assert "qmd" in result


def test_collect_mcp_servers_skips_qmd_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    result = engine._collect_mcp_servers(Config())
    assert "qmd" not in result


def test_collect_mcp_servers_includes_engram_when_enabled_and_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)

    cfg = Config()
    cfg.memory.engram.enabled = True

    result = engine._collect_mcp_servers(cfg)
    assert "engram" in result
    assert result["engram"]["command"] == "engram"


def test_collect_mcp_servers_skips_engram_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)

    cfg = Config()
    cfg.memory.engram.enabled = False

    result = engine._collect_mcp_servers(cfg)
    assert "engram" not in result


def test_collect_mcp_servers_skips_engram_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)

    cfg = Config()
    cfg.memory.engram.enabled = True

    result = engine._collect_mcp_servers(cfg)
    assert "engram" not in result


def test_collect_mcp_servers_omits_graphify_on_cli_only_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graphify was CLI/skill-only before 0.9, which shipped a graphify-mcp binary.

    Presence of the binary — not the config flag alone — decides whether the
    entry ships, so installs pinned to an older release keep working.
    """
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_mcp_available", lambda: False)

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    result = engine._collect_mcp_servers(cfg)
    assert "graphify" not in result


def test_collect_mcp_servers_includes_graphify_when_enabled_and_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upstream ships a graphify-mcp binary; structure queries should not need the skill."""
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_mcp_available", lambda: True)

    cfg = Config()
    cfg.knowledge.structure.enabled = True
    result = engine._collect_mcp_servers(cfg)

    assert result["graphify"] == {"command": "graphify-mcp", "args": []}


def test_collect_mcp_servers_skips_graphify_when_structure_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_mcp_available", lambda: True)

    cfg = Config()
    cfg.knowledge.structure.enabled = False
    assert "graphify" not in engine._collect_mcp_servers(cfg)


def test_collect_mcp_servers_skips_graphify_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI can be installed without the MCP binary on older releases."""
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_mcp_available", lambda: False)

    cfg = Config()
    cfg.knowledge.structure.enabled = True
    assert "graphify" not in engine._collect_mcp_servers(cfg)
