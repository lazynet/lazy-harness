"""MCP servers a profile's adapter does not place in a fresh config plan.

Codex and Copilot both return ``""`` from ``mcp_config_file()`` but mean
opposite things by it, so the filename cannot be the oracle. The base contract
says empty means merged into the main file, while Copilot uses it for no MCP
document at all; comparing plans with and without servers tests the behavior
that deploy actually runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from lazy_harness.core.config import Config


@dataclass(frozen=True)
class McpServerGap:
    """Detected servers omitted from one profile's fresh adapter plan."""

    profile: str
    agent: str
    servers: tuple[str, ...]


def mcp_gap_for_profile(
    cfg: Config,
    profile: str,
    *,
    servers: dict[str, dict] | None = None,
) -> McpServerGap | None:
    """Return the detected servers this profile's adapter ignores, if any."""
    from lazy_harness.agents.registry import agent_for_profile, binary_for_profile
    from lazy_harness.deploy.engine import _collect_mcp_servers

    detected = _collect_mcp_servers(cfg) if servers is None else servers
    if not detected:
        return None

    adapter = agent_for_profile(cfg, profile)
    binary = binary_for_profile(cfg, profile)
    with_servers = adapter.plan_config({}, detected, {}, binary=binary)
    without_servers = adapter.plan_config({}, {}, {}, binary=binary)
    if with_servers != without_servers:
        return None

    return McpServerGap(
        profile=profile,
        agent=adapter.name,
        servers=tuple(detected),
    )


def collect_mcp_gaps(
    cfg: Config,
    *,
    servers: dict[str, dict] | None = None,
) -> list[McpServerGap]:
    """Collect MCP placement gaps across every profile in the config."""
    from lazy_harness.deploy.engine import _collect_mcp_servers, selected_profiles

    detected = _collect_mcp_servers(cfg) if servers is None else servers
    if not detected:
        return []

    gaps: list[McpServerGap] = []
    for profile in selected_profiles(cfg, None):
        gap = mcp_gap_for_profile(cfg, profile, servers=detected)
        if gap is not None:
            gaps.append(gap)
    return gaps
