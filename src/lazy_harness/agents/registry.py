"""Agent discovery and registration."""

from __future__ import annotations

from lazy_harness.agents.base import AgentAdapter
from lazy_harness.agents.claude_code import ClaudeCodeAdapter


class AgentNotFoundError(Exception):
    """Raised when requested agent type is not registered."""


_AGENTS: dict[str, type] = {
    "claude-code": ClaudeCodeAdapter,
}


def get_agent(agent_type: str) -> AgentAdapter:
    """Get an agent adapter instance by type name."""
    cls = _AGENTS.get(agent_type)
    if cls is None:
        raise AgentNotFoundError(f"Agent '{agent_type}' not found. Available: {', '.join(_AGENTS)}")
    return cls()


def list_agents() -> list[str]:
    """Return list of registered agent type names."""
    return list(_AGENTS.keys())
