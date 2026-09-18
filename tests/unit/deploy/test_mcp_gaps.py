from __future__ import annotations

import pytest

from lazy_harness.agents.registry import NullAdapter
from lazy_harness.core.config import Config, ProfileEntry

SERVERS = {
    "qmd": {"command": "qmd", "args": ["mcp"]},
    "engram": {"command": "engram", "args": ["mcp", "serve"]},
    "graphify": {"command": "graphify-mcp"},
}


def _cfg(agent: str) -> Config:
    cfg = Config()
    cfg.agent.type = agent
    cfg.profiles.default = "p1"
    cfg.profiles.items = {
        "p1": ProfileEntry(config_dir="~/.agent-p1", agent=agent),
    }
    return cfg


def test_real_copilot_adapter_reports_every_detected_server() -> None:
    from lazy_harness.deploy.mcp_gaps import mcp_gap_for_profile

    gap = mcp_gap_for_profile(_cfg("copilot"), "p1", servers=SERVERS)

    assert gap is not None
    assert gap.profile == "p1"
    assert gap.agent == "copilot"
    assert gap.servers == ("qmd", "engram", "graphify")


def test_real_copilot_adapter_is_silent_when_no_server_is_detected() -> None:
    from lazy_harness.deploy.mcp_gaps import mcp_gap_for_profile

    assert mcp_gap_for_profile(_cfg("copilot"), "p1", servers={}) is None


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_real_adapter_that_places_servers_has_no_gap(agent: str) -> None:
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.deploy.mcp_gaps import mcp_gap_for_profile

    assert get_agent(agent).plan_config({}, SERVERS, {}, binary="lh") != get_agent(
        agent
    ).plan_config({}, {}, {}, binary="lh")
    assert mcp_gap_for_profile(_cfg(agent), "p1", servers=SERVERS) is None


class _ServerBlindAdapter(NullAdapter):
    @property
    def name(self) -> str:
        return "server-blind"

    def plan_config(self, hooks, servers, existing, *, binary=None):
        return []


def test_oracle_uses_the_plan_not_the_adapter_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.agents import registry
    from lazy_harness.deploy.mcp_gaps import mcp_gap_for_profile

    monkeypatch.setitem(registry._AGENTS, "server-blind", _ServerBlindAdapter)

    gap = mcp_gap_for_profile(_cfg("server-blind"), "p1", servers=SERVERS)

    assert gap is not None
    assert gap.agent == "server-blind"


def test_collect_mcp_gaps_checks_every_declared_profile() -> None:
    from lazy_harness.deploy.mcp_gaps import McpServerGap, collect_mcp_gaps

    cfg = _cfg("copilot")
    cfg.profiles.items["cx"] = ProfileEntry(config_dir="~/.codex-test", agent="codex")

    assert collect_mcp_gaps(cfg, servers=SERVERS) == [
        McpServerGap(
            profile="p1",
            agent="copilot",
            servers=("qmd", "engram", "graphify"),
        )
    ]
