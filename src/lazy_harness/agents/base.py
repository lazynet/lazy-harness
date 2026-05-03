"""Agent adapter protocol — defines what an agent adapter must expose."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol that all agent adapters must implement."""

    @property
    def name(self) -> str:
        """Unique identifier for this agent type."""
        ...

    def config_dir(self, profile_config_dir: str) -> Path:
        """Resolve the agent's config directory for a profile."""
        ...

    def supported_hooks(self) -> list[str]:
        """Return list of hook events this agent supports."""
        ...

    def generate_hook_config(self, hooks: dict[str, list[str]]) -> dict:
        """Generate agent-native hook config (e.g., settings.json for Claude Code)."""
        ...

    def generate_mcp_config(self, servers: dict[str, dict]) -> dict:
        """Generate agent-native MCP server config block.

        `servers` is a mapping of server name -> declarative entry
        (`{"command": str, "args": list[str], "env": dict[str, str] | None}`).
        Returns a dict ready to merge into the agent's settings file.
        """
        ...

    def resolve_binary(self) -> Path | None:
        """Locate the agent's executable on disk.

        Returns the absolute path, or None if not found. Implementations
        should prefer well-known install locations (e.g. version-managed
        directories) over a generic PATH lookup, and must avoid resolving
        to wrappers that would shell back into `lh run` (recursion).
        """
        ...

    def env_var(self) -> str:
        """Name of the environment variable that selects the profile config dir."""
        ...
