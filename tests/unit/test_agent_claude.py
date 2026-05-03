"""Tests for Claude Code agent adapter."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_claude_adapter_name() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    assert adapter.name == "claude-code"


def test_claude_adapter_config_dir() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter.config_dir("~/.claude-personal")
    assert result == Path.home() / ".claude-personal"


def test_claude_adapter_supported_hooks() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    hooks = adapter.supported_hooks()
    assert "session_start" in hooks
    assert "session_stop" in hooks
    assert "session_end" in hooks
    assert "pre_compact" in hooks


def test_claude_adapter_maps_session_end_to_SessionEnd() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter.generate_hook_config({"session_end": ["lh hook session-end"]})
    assert "SessionEnd" in result
    assert result["SessionEnd"][0]["hooks"][0]["command"] == "lh hook session-end"


def test_registry_get_claude() -> None:
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    assert adapter.name == "claude-code"


def test_registry_unknown_agent() -> None:
    from lazy_harness.agents.registry import AgentNotFoundError, get_agent

    with pytest.raises(AgentNotFoundError):
        get_agent("unknown-agent")


def test_registry_list_agents() -> None:
    from lazy_harness.agents.registry import list_agents

    agents = list_agents()
    assert "claude-code" in agents


def test_claude_adapter_env_var() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().env_var() == "CLAUDE_CONFIG_DIR"


def test_claude_resolve_binary_picks_newest_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    fake_home = tmp_path / "home"
    versions = fake_home / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True)
    older = versions / "2.0.0"
    older.write_text("#!/bin/sh\n")
    older.chmod(0o755)
    newer = versions / "2.1.0"
    newer.write_text("#!/bin/sh\n")
    newer.chmod(0o755)
    # Force newer's mtime to be strictly greater than older's
    os.utime(older, (1_000_000_000, 1_000_000_000))
    os.utime(newer, (2_000_000_000, 2_000_000_000))

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = ClaudeCodeAdapter().resolve_binary()
    assert result == newer


def test_claude_resolve_binary_falls_back_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents import claude_code as cc_mod
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(cc_mod.shutil, "which", lambda name: "/usr/local/bin/claude")

    result = ClaudeCodeAdapter().resolve_binary()
    assert result == Path("/usr/local/bin/claude")


def test_claude_resolve_binary_returns_none_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents import claude_code as cc_mod
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(cc_mod.shutil, "which", lambda name: None)

    assert ClaudeCodeAdapter().resolve_binary() is None


def test_generate_hook_config_uses_bash_matcher_for_pre_tool_use() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter.generate_hook_config({"pre_tool_use": ["pre-tool-use-security"]})
    assert "PreToolUse" in result
    entries = result["PreToolUse"]
    assert len(entries) == 1
    assert entries[0]["matcher"] == "Bash"


def test_generate_hook_config_uses_edit_write_matcher_for_post_tool_use() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter.generate_hook_config({"post_tool_use": ["post-tool-use-format"]})
    assert "PostToolUse" in result
    entries = result["PostToolUse"]
    assert len(entries) == 1
    assert entries[0]["matcher"] == "Edit|Write"


def test_generate_hook_config_keeps_empty_matcher_for_other_events() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter.generate_hook_config({"session_start": ["context-inject"]})
    entries = result["SessionStart"]
    assert entries[0]["matcher"] == ""


def test_claude_adapter_generate_mcp_config_returns_dict() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    servers = {
        "qmd": {"command": "qmd", "args": ["mcp"]},
    }
    result = adapter.generate_mcp_config(servers)
    assert isinstance(result, dict)
    assert "mcpServers" in result
    assert "qmd" in result["mcpServers"]
    assert result["mcpServers"]["qmd"]["command"] == "qmd"
    assert result["mcpServers"]["qmd"]["args"] == ["mcp"]


def test_claude_adapter_generate_mcp_config_empty() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().generate_mcp_config({})
    assert result == {"mcpServers": {}}


def test_claude_adapter_generate_mcp_config_passes_env() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    servers = {
        "engram": {
            "command": "engram",
            "args": ["mcp"],
            "env": {"ENGRAM_PORT": "7437"},
        },
    }
    result = ClaudeCodeAdapter().generate_mcp_config(servers)
    assert result["mcpServers"]["engram"]["env"] == {"ENGRAM_PORT": "7437"}
