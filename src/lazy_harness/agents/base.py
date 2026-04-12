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
