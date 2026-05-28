"""Agent discovery and registration."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.agents.base import AgentAdapter
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.core.paths import expand_path


class AgentNotFoundError(Exception):
    """Raised when requested agent type is not registered."""


class NullAdapter:
    """Sentinel adapter for testing — returns None/empty for all optional methods."""

    @property
    def name(self) -> str:
        return "null"

    def config_dir(self, profile_config_dir: str) -> Path:
        return expand_path(profile_config_dir)

    def env_var(self) -> str:
        return ""

    def resolve_binary(self) -> Path | None:
        return None

    def supported_hooks(self) -> list[str]:
        return []

    def generate_hook_config(self, hooks: dict) -> dict:
        return {}

    def generate_mcp_config(self, servers: dict) -> dict:
        return {}

    def global_config_link(self) -> Path | None:
        return None

    def mcp_config_file(self) -> str:
        return ""

    def session_dirs(self) -> dict[str, str]:
        return {"sessions": "", "logs": "", "queue": ""}

    def system_doc_name(self) -> str:
        return ""


_AGENTS: dict[str, type] = {
    "claude-code": ClaudeCodeAdapter,
    "null": NullAdapter,
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
