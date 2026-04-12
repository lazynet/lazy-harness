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
    assert "pre_compact" in hooks


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
