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


def test_deploy_mcp_servers_writes_settings_when_qmd_available(
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

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert "mcpServers" in settings
    assert settings["mcpServers"]["qmd"]["command"] == "qmd"


def test_deploy_mcp_servers_preserves_existing_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / ".claude-test"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text(
        json.dumps({"hooks": {"SessionStart": [{"matcher": "", "hooks": []}]}})
    )

    monkeypatch.setattr(
        engine,
        "_collect_mcp_servers",
        lambda cfg: {"qmd": {"command": "qmd", "args": ["mcp"]}},
    )

    engine.deploy_mcp_servers(_make_cfg(profile_dir))

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert "hooks" in settings
    assert "mcpServers" in settings


def test_deploy_mcp_servers_noop_when_no_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / ".claude-test"
    profile_dir.mkdir()
    monkeypatch.setattr(engine, "_collect_mcp_servers", lambda cfg: {})

    engine.deploy_mcp_servers(_make_cfg(profile_dir))

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


def test_collect_mcp_servers_includes_graphify_when_enabled_and_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: True)

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    result = engine._collect_mcp_servers(cfg)
    assert "graphify" in result
    assert result["graphify"]["command"] == "graphify"


def test_collect_mcp_servers_skips_graphify_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: True)

    cfg = Config()
    cfg.knowledge.structure.enabled = False

    result = engine._collect_mcp_servers(cfg)
    assert "graphify" not in result


def test_collect_mcp_servers_skips_graphify_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: False)

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    result = engine._collect_mcp_servers(cfg)
    assert "graphify" not in result
