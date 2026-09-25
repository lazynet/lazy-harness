"""A builtin declared for named agents is deployed only to their profiles.

`pre-tool-use-graph-assist` is Claude Code only: Codex keeps graphify's
upstream guard as the control group (graph-assist design §2), and
`config.toml` is shared, so the scoping has to be the builtin's own. Deploy
names each omission, the same way it names a signal gap.
"""

from __future__ import annotations

import pytest

from lazy_harness.core.config import Config, HookEventConfig, ProfileEntry

HOOK = "pre-tool-use-graph-assist"


def _cfg() -> Config:
    cfg = Config()
    cfg.profiles.default = "cl"
    cfg.profiles.items = {
        "cl": ProfileEntry(config_dir="~/.claude-cl", agent="claude-code"),
        "cx": ProfileEntry(config_dir="~/.codex-cx", agent="codex"),
    }
    cfg.hooks = {"pre_tool_use": HookEventConfig(scripts=[HOOK])}
    return cfg


def _deployed(entries: dict) -> bool:
    return any(HOOK in e.command for e in entries.get("pre_tool_use", []))


def test_agent_scoped_builtin_reaches_its_agent_only(capsys: pytest.CaptureFixture[str]) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    cfg = _cfg()

    assert _deployed(_hook_entries_for(cfg, "cl", "lh"))
    assert not _deployed(_hook_entries_for(cfg, "cx", "lh"))
    assert f"· {HOOK} omitted in 'cx': declared for agents claude-code" in capsys.readouterr().out


def test_builtin_agents_reads_the_spec() -> None:
    from lazy_harness.hooks.loader import builtin_agents

    assert builtin_agents(HOOK) == frozenset({"claude-code"})
    assert builtin_agents("pre-tool-use-read-size") == frozenset()
    assert builtin_agents("not-a-hook") == frozenset()


def test_doctor_and_deploy_agree_on_an_agent_scoped_builtin() -> None:
    """Coherence audit 2026-09-25 (high): deploy omitted the hook from the Codex
    profile while `lh doctor` reported it as deployed there with an inert
    operation, because the scoping lived in deploy alone. One resolver now."""
    from lazy_harness.agents.registry import agent_for_profile
    from lazy_harness.deploy.defaults import merge_with_defaults
    from lazy_harness.hooks.event_surface import operation_gaps_for_profile
    from lazy_harness.hooks.signal_gaps import gaps_for_profile

    cfg = _cfg()
    codex = agent_for_profile(cfg, "cx")

    assert HOOK not in merge_with_defaults(cfg.hooks, codex)["pre_tool_use"]
    assert HOOK not in {g.hook for g in operation_gaps_for_profile(cfg, "cx")}
    assert HOOK not in {g.hook for g in gaps_for_profile(cfg, "cx")}
    assert HOOK in merge_with_defaults(cfg.hooks, agent_for_profile(cfg, "cl"))["pre_tool_use"]


def test_agent_scoped_omissions_name_what_the_merge_dropped() -> None:
    from lazy_harness.agents.registry import agent_for_profile
    from lazy_harness.deploy.defaults import agent_scoped_omissions

    cfg = _cfg()

    assert agent_scoped_omissions(cfg.hooks, agent_for_profile(cfg, "cx")) == [
        ("pre_tool_use", HOOK)
    ]
    assert agent_scoped_omissions(cfg.hooks, agent_for_profile(cfg, "cl")) == []
