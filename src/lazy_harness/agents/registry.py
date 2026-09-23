"""Agent discovery and registration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from lazy_harness.agents.base import (
    AgentAdapter,
    Bypass,
    HookDecision,
    HookEvent,
    HookOutput,
    HookSupport,
)
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.agents.codex import CodexAdapter
from lazy_harness.agents.copilot import CopilotAdapter
from lazy_harness.core.paths import expand_path

if TYPE_CHECKING:
    from lazy_harness.core.config import Config


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

    def hook_events(self) -> dict[str, HookSupport]:
        return {}

    def bypass_argv(self, level: Bypass) -> list[str] | None:
        """Launches nothing, so it has no argv and no level on it — the same
        shape as `format_hook_output` above: the sentinel states the absence
        rather than returning something empty that a caller would forward."""
        return None

    def parse_hook_input(self, event: str, payload: dict, *, profile: str) -> HookEvent:
        return HookEvent(
            event=event,
            profile=profile,
            session_id="",
            cwd=Path(),
            transcript_path=None,
            raw=payload,
        )

    def format_hook_output(self, event: HookEvent, decision: HookDecision) -> HookOutput:
        """Delivers no event, so honours no verdict — and says so rather than
        emitting nothing, which on a blocking hook would read as approval."""
        if decision.verdict is not None:
            raise ValueError(f"null honours no verdict on {event.event!r}")
        return HookOutput(stdout=None, stderr="", exit_code=0)

    def global_config_link(self) -> Path | None:
        return None

    def default_home(self) -> Path:
        return Path.home() / f".{self.name}"

    def skill_root(self, profile_config_dir: str) -> Path | None:
        return None

    def mcp_config_file(self) -> str:
        return ""

    def session_dirs(self) -> dict[str, str]:
        return {"sessions": "", "logs": "", "queue": ""}

    def system_docs(self) -> list[Path]:
        return []

    def credentials_file(self) -> str | None:
        return None

    def process_name(self) -> str:
        return ""


_AGENTS: dict[str, type] = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "copilot": CopilotAdapter,
    "null": NullAdapter,
}

# The profile-name prefix each agent uses (`~/.<prefix>-<identity>`), one
# entry per `_AGENTS` key. Not the registry key itself: "claude-code" would
# give `~/.claude-code-<identity>`, and every profile on disk is `~/.claude-*`.
PROFILE_PREFIXES: dict[str, str] = {
    "claude-code": "claude",
    "codex": "codex",
    "copilot": "copilot",
    "null": "null",
}


def profile_prefix(agent_name: str) -> str:
    """The profile-name prefix for a registered agent, or a `ValueError`."""
    prefix = PROFILE_PREFIXES.get(agent_name)
    if prefix is None:
        raise ValueError(f"agent {agent_name!r} has no profile prefix")
    return prefix


def get_agent(agent_type: str) -> AgentAdapter:
    """Get an agent adapter instance by type name."""
    cls = _AGENTS.get(agent_type)
    if cls is None:
        raise AgentNotFoundError(f"Agent '{agent_type}' not found. Available: {', '.join(_AGENTS)}")
    return cls()


def agent_for_profile(cfg: Config, profile_name: str) -> AgentAdapter:
    """The agent a single profile runs — `[profiles.<name>].agent`, else `[agent].type`.

    Every path that needs to know which agent a profile runs resolves it here.
    The deploy loops previously resolved `cfg.agent.type` once, above their own
    profile loop, so a per-profile agent could never take effect: each root got
    the global agent's env var and the global agent's config shape.

    An unknown profile name falls back to the global agent rather than raising.
    Callers iterate `cfg.profiles.items`, so the name is theirs; the failure that
    matters is an *unregistered agent*, which `get_agent` refuses loudly.
    """
    entry = cfg.profiles.items.get(profile_name)
    declared = entry.agent if entry is not None else ""
    return get_agent(declared or cfg.agent.type)


# The launcher a profile's hooks reach when it declares no `harness_binary`.
# `deploy.engine` imports it rather than retyping the name: the generator, the
# classifier and this resolver all have to agree on it or a redeploy stops
# recognising its own entries.
DEFAULT_HARNESS_BINARY = "lh"


def binary_for_profile(cfg: Config, profile_name: str) -> str:
    """The launcher one profile's hooks run — `[profiles.<name>].harness_binary`,
    else `DEFAULT_HARNESS_BINARY`.

    Shaped after `agent_for_profile`, including the fallback for an unknown
    profile name: callers iterate `cfg.profiles.items`, so the name is theirs,
    and resolving to an empty string would generate a command `execvp` cannot
    run. Unlike an agent there is no registry to validate against — the name is
    resolved from `PATH` at hook time, and the harness cannot know what is
    installed on the machine the settings file converges to.
    """
    entry = cfg.profiles.items.get(profile_name)
    declared = entry.harness_binary if entry is not None else ""
    return declared or DEFAULT_HARNESS_BINARY


def list_agents() -> list[str]:
    """Return list of registered agent type names."""
    return list(_AGENTS.keys())
