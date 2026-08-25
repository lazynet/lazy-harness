"""Agent adapter protocol — defines what an agent adapter must expose."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

HEADLESS_TIERS: tuple[str, ...] = ("fast", "balanced", "deep")
"""Provider-neutral capability tiers a caller may ask for.

The vocabulary lives here so the CLI and every adapter agree on it; the
mapping from a tier to a concrete model id is the adapter's business.
"""


@dataclass(frozen=True)
class HeadlessResult:
    """One headless invocation, normalised across providers.

    Token fields are `None` when the provider did not report them — never 0.
    A zero enters a cost report as a fact, and "this provider has no prompt
    cache" is not the same fact as "this call cached nothing".
    """

    success: bool
    output: str
    exit_code: int
    cost_usd: float | None = None
    duration_ms: int | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    num_turns: int | None = None
    raw: dict | None = None


@runtime_checkable
class HeadlessAgent(Protocol):
    """Optional capability: an agent that can be driven non-interactively.

    Deliberately separate from `AgentAdapter`. An adapter that cannot be
    invoked headlessly simply does not implement these, and `lh exec` refuses
    it up front instead of exec'ing something whose output it cannot parse.
    """

    def resolve_model(self, *, tier: str | None, explicit: str | None) -> str | None:
        """Resolve a model id. `explicit` wins; `None`/`None` means provider default.

        Raises ValueError for a tier this provider does not map.
        """
        ...

    def headless_argv(self, *, model: str | None, allowed_tools: list[str] | None) -> list[str]:
        """Build the argv that follows argv[0], excluding the prompt.

        The prompt travels on stdin, so argv stays bounded regardless of
        prompt size. `allowed_tools` is tri-state: `None` leaves the
        provider's own policy alone, `[]` denies every tool it can be told
        to deny, and a list grants exactly those.
        """
        ...

    def parse_headless_result(self, stdout: str, exit_code: int) -> HeadlessResult:
        """Normalise the provider's stdout into a `HeadlessResult`.

        Must not raise: unparseable output degrades to `output=stdout`,
        `raw=None`, and metadata left `None`.
        """
        ...


@dataclass(frozen=True)
class HookEntry:
    """One hook command to be installed under an event.

    `matcher` overrides the agent's default matcher for this event when set.
    Used so a single event (e.g. `pre_tool_use`) can dispatch hooks to
    different tool matchers (`Bash` vs `Edit|Write`).
    """

    command: str
    matcher: str | None = None


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

    def global_config_link(self) -> Path | None:
        """Canonical global symlink for this agent (e.g. ~/.claude).

        Return None if the agent does not use a global symlink convention.
        `lh deploy` only creates the symlink when this is non-None.
        """
        ...

    def mcp_config_file(self) -> str:
        """Filename inside the config dir that holds MCP server config.

        Claude Code: '.claude.json'. Return empty string if MCP config
        is merged into the main settings file.
        """
        ...

    def session_dirs(self) -> dict[str, str]:
        """Subdirectory names for agent-managed session artefacts.

        Keys: 'sessions', 'logs', 'queue'. Empty string means not available.
        Claude Code: {'sessions': 'projects', 'logs': 'logs', 'queue': 'queue'}
        """
        ...

    def system_doc_name(self) -> str:
        """Primary system-instruction document filename (e.g. 'CLAUDE.md').

        Return empty string for agents that use a different injection mechanism.
        """
        ...

    def process_name(self) -> str:
        """Process name to use as argv[0] when exec'ing the resolved binary.

        Lets process-detection tools recognize the agent by name even when
        `resolve_binary()` resolves to a versioned install path. Return empty
        string to fall back to the resolved binary path as argv[0].
        """
        ...
