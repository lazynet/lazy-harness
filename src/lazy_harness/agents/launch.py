"""Resolution shared by every path that launches the configured agent.

`lh run` and `lh exec` answer the same question — which profile, which
adapter, which binary, which environment — and must not answer it twice.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.agents.base import AgentAdapter, HeadlessAgent
from lazy_harness.agents.registry import AgentNotFoundError, agent_for_profile
from lazy_harness.core.config import Config
from lazy_harness.core.paths import expand_path
from lazy_harness.core.profiles import ProfileError, resolve_profile_with_source
from lazy_harness.core.secrets import SecretsError, overlay_profile_secrets, secrets_dir_for


class LaunchError(Exception):
    """A launch could not be resolved. `kind` is a stable machine-readable tag."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class LaunchPlan:
    profile: str
    profile_source: str
    config_dir: Path
    adapter: AgentAdapter
    binary: Path
    env: dict[str, str]


def resolve_launch(
    cfg: Config,
    cwd: Path | None = None,
    profile_override: str | None = None,
    *,
    require_headless: bool = False,
) -> LaunchPlan:
    """Resolve everything needed to start the agent, or raise `LaunchError`.

    `require_headless` is checked before the binary is located: an agent that
    cannot be driven non-interactively is the more useful error to report.
    """
    if not cfg.profiles.items:
        raise LaunchError("no-profiles", "No profiles configured. Run `lh init`.")

    try:
        resolution = resolve_profile_with_source(cfg, cwd, profile_override)
    except ProfileError as e:
        raise LaunchError("unknown-profile", str(e)) from e

    config_dir = expand_path(cfg.profiles.items[resolution.name].config_dir)

    # Resolved from the profile just resolved above, not from `[agent].type`:
    # `config_dir` on the line before is this profile's, so a global adapter
    # would hand one agent's env var the directory of another agent's home.
    try:
        adapter = agent_for_profile(cfg, resolution.name)
    except AgentNotFoundError as e:
        raise LaunchError("unknown-agent", str(e)) from e

    if require_headless and not isinstance(adapter, HeadlessAgent):
        raise LaunchError(
            "agent-not-headless",
            f"Agent '{adapter.name}' does not support headless execution.",
        )

    binary = adapter.resolve_binary()
    if binary is None:
        raise LaunchError("binary-not-found", f"Cannot locate {adapter.name} binary.")

    env = os.environ.copy()
    # The agent's credential is one global variable and its stored credentials
    # live inside `config_dir`, so a second profile backed by a second account
    # would otherwise authenticate as the first — silently.
    if adapter.env_var():
        env[adapter.env_var()] = str(config_dir)
    # A declared secrets file that cannot be read stops the launch (ADR-045 D2).
    # Continuing would exec the agent with whichever account the ambient
    # environment already carries, which is the one thing the file exists to
    # prevent — and it would do it with nothing on the channel to say so.
    try:
        env = overlay_profile_secrets(env, resolution.name, secrets_dir=secrets_dir_for(cfg))
    except SecretsError as e:
        raise LaunchError("secrets-unreadable", str(e)) from e

    return LaunchPlan(
        profile=resolution.name,
        profile_source=resolution.source,
        config_dir=config_dir,
        adapter=adapter,
        binary=binary,
        env=env,
    )
