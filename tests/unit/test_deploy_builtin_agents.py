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
