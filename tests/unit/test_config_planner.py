"""ClaudeCodeAdapter as a ConfigPlanner — step 3 of the multi-agent design.

The acceptance test the design names is byte identity: `plan_config` must
produce exactly the `settings.json` and `.claude.json` that `deploy_hooks` and
`deploy_mcp_servers` write today, for the same inputs. Structural equality is
not enough — key order, indentation and the trailing newline are all part of
what a chezmoi-managed profile diffs against.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.agents.base import ConfigPlanner, HookEntry
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.core.config import (
    Config,
    ExternalHookConfig,
    HarnessConfig,
    HookEventConfig,
    ProfileEntry,
    ProfilesConfig,
)

SETTINGS = Path("settings.json")
CLAUDE_JSON = Path(".claude.json")
PROFILE = "personal"

MCP_SERVERS: dict[str, dict] = {
    "qmd": {"command": "qmd", "args": ["mcp"]},
    "engram": {"command": "engram", "args": ["mcp", "serve"], "env": {"ENGRAM_DB": "/tmp/e.db"}},
}


def _cfg_with_profile(profile_dir: Path, hooks: dict[str, HookEventConfig] | None = None) -> Config:
    return Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default=PROFILE,
            items={PROFILE: ProfileEntry(config_dir=str(profile_dir), roots=["~"])},
        ),
        hooks=hooks or {},
    )


def _entries_for(cfg: Config, profile: str, binary: str) -> dict[str, list[HookEntry]]:
    """Rebuild, independently of the adapter, the hook entries the engine feeds it.

    This mirrors `deploy_hooks.entries_for` so the two halves of the comparison
    start from the same generated commands. It is deliberately a separate
    derivation rather than a call into the engine's closure: if the adapter ever
    starts generating its own commands, this test still pins the old ones.
    """
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.deploy.defaults import merge_with_defaults
    from lazy_harness.deploy.engine import hook_command
    from lazy_harness.hooks.loader import resolve_script_names

    agent = get_agent(cfg.agent.type)
    effective = merge_with_defaults(cfg.hooks, agent)

    entries: dict[str, list[HookEntry]] = {}
    for event_name, script_names in effective.items():
        if not script_names:
            continue
        resolved = resolve_script_names(script_names, event=event_name)
        if not resolved:
            continue
        entries[event_name] = [
            HookEntry(
                command=hook_command(hook, profile=profile, binary=binary),
                matcher=hook.matcher,
            )
            for hook in resolved
        ]
    for event_name, event_cfg in cfg.hooks.items():
        for ext in event_cfg.external:
            entries.setdefault(event_name, []).append(
                HookEntry(command=ext.command, matcher=ext.matcher)
            )
    return entries


def _op_for(ops: list, path: Path):
    matching = [op for op in ops if op.relative_path == path]
    assert len(matching) <= 1, f"{path} planned more than once: {len(matching)} ops"
    return matching[0] if matching else None


# --- the protocol itself -------------------------------------------------


def test_adapter_satisfies_config_planner_protocol() -> None:
    assert isinstance(ClaudeCodeAdapter(), ConfigPlanner)


def test_config_targets_names_settings_and_the_mcp_file() -> None:
    adapter = ClaudeCodeAdapter()
    targets = adapter.config_targets()

    assert targets == [SETTINGS, Path(adapter.mcp_config_file())]
    assert all(not t.is_absolute() for t in targets), "targets are relative to the config dir"


# --- byte identity against the engine as it writes today -----------------


def test_settings_bytes_match_deploy_hooks_on_a_fresh_profile(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import deploy_hooks

    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir)
    deploy_hooks(cfg)
    expected = (profile_dir / "settings.json").read_text()

    ops = ClaudeCodeAdapter().plan_config(_entries_for(cfg, PROFILE, "lh"), {}, {})

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert op.artifact.content == expected


def test_settings_bytes_match_deploy_hooks_over_an_existing_document(tmp_path: Path) -> None:
    """The interesting file: foreign entries, a repairable one, a stale harness
    entry, an event the harness does not model, and unrelated top-level keys."""
    from lazy_harness.deploy.engine import deploy_hooks

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    pre = {
        "model": "opus",
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "/usr/local/bin/my-manual-hook"}],
                },
                {
                    "matcher": None,
                    "hooks": [{"type": "command", "command": "/usr/local/bin/broken-hook"}],
                },
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "lh hook retired_hook --profile personal"}
                    ],
                },
            ],
            "SomeFutureEvent": [
                {"matcher": "", "hooks": [{"type": "command", "command": "other-tool"}]}
            ],
        },
    }
    original = json.dumps(pre, indent=2) + "\n"
    (profile_dir / "settings.json").write_text(original)

    cfg = _cfg_with_profile(profile_dir)
    deploy_hooks(cfg)
    expected = (profile_dir / "settings.json").read_text()

    ops = ClaudeCodeAdapter().plan_config(
        _entries_for(cfg, PROFILE, "lh"), {}, {SETTINGS: original}
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert op.artifact.content == expected


def test_settings_bytes_match_deploy_hooks_with_external_hooks(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import deploy_hooks

    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(
        profile_dir,
        hooks={
            "pre_tool_use": HookEventConfig(
                external=[ExternalHookConfig(command="other-tool guard", matcher="Write")]
            )
        },
    )
    deploy_hooks(cfg)
    expected = (profile_dir / "settings.json").read_text()

    ops = ClaudeCodeAdapter().plan_config(_entries_for(cfg, PROFILE, "lh"), {}, {})

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert op.artifact.content == expected


def test_settings_bytes_match_deploy_hooks_for_a_non_default_binary(tmp_path: Path) -> None:
    """A beta profile points its hooks at `lh-beta`; the stamp and the ownership
    allow-list both have to follow, or the next deploy duplicates every hook."""
    from lazy_harness.deploy.engine import deploy_hooks

    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir)
    cfg.profiles.items[PROFILE].harness_binary = "lh-beta"
    deploy_hooks(cfg)
    expected = (profile_dir / "settings.json").read_text()

    ops = ClaudeCodeAdapter().plan_config(
        _entries_for(cfg, PROFILE, "lh-beta"), {}, {}, binary="lh-beta"
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert op.artifact.content == expected


def test_settings_bytes_match_deploy_hooks_on_a_corrupt_document(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import deploy_hooks

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    original = "{ this is not json"
    (profile_dir / "settings.json").write_text(original)

    cfg = _cfg_with_profile(profile_dir)
    deploy_hooks(cfg)
    expected = (profile_dir / "settings.json").read_text()

    ops = ClaudeCodeAdapter().plan_config(
        _entries_for(cfg, PROFILE, "lh"), {}, {SETTINGS: original}
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert op.artifact.content == expected


def test_claude_json_bytes_match_deploy_mcp_servers_on_a_fresh_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    monkeypatch.setattr(engine, "_collect_mcp_servers", lambda cfg: MCP_SERVERS)
    engine.deploy_mcp_servers(_cfg_with_profile(profile_dir))
    expected = (profile_dir / ".claude.json").read_text()

    ops = ClaudeCodeAdapter().plan_config({}, MCP_SERVERS, {})

    op = _op_for(ops, CLAUDE_JSON)
    assert op is not None and op.artifact is not None
    assert op.artifact.content == expected


def test_claude_json_bytes_match_deploy_mcp_servers_over_an_existing_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    pre = {
        "numStartups": 12,
        "mcpServers": {
            "someone-elses": {"command": "other", "args": []},
            "qmd": {"command": "stale-qmd", "args": []},
        },
    }
    original = json.dumps(pre, indent=2) + "\n"
    (profile_dir / ".claude.json").write_text(original)

    monkeypatch.setattr(engine, "_collect_mcp_servers", lambda cfg: MCP_SERVERS)
    engine.deploy_mcp_servers(_cfg_with_profile(profile_dir))
    expected = (profile_dir / ".claude.json").read_text()

    ops = ClaudeCodeAdapter().plan_config({}, MCP_SERVERS, {CLAUDE_JSON: original})

    op = _op_for(ops, CLAUDE_JSON)
    assert op is not None and op.artifact is not None
    assert op.artifact.content == expected


def test_both_targets_planned_in_one_call(tmp_path: Path) -> None:
    cfg = _cfg_with_profile(tmp_path / "profile")

    ops = ClaudeCodeAdapter().plan_config(_entries_for(cfg, PROFILE, "lh"), MCP_SERVERS, {})

    assert [op.relative_path for op in ops] == [SETTINGS, CLAUDE_JSON]


# --- when nothing is planned ---------------------------------------------


def test_no_hooks_plans_no_settings_write(tmp_path: Path) -> None:
    """`deploy_hooks` leaves settings.json alone when nothing resolves, and a
    plan that emitted an empty hooks block instead would uninstall every
    foreign entry on a profile with no harness hooks configured."""
    ops = ClaudeCodeAdapter().plan_config({}, MCP_SERVERS, {SETTINGS: '{"hooks": {}}\n'})

    assert _op_for(ops, SETTINGS) is None


def test_no_servers_plans_no_mcp_write() -> None:
    cfg = _cfg_with_profile(Path("/nonexistent"))

    ops = ClaudeCodeAdapter().plan_config(_entries_for(cfg, PROFILE, "lh"), {}, {})

    assert _op_for(ops, CLAUDE_JSON) is None


def test_nothing_to_deploy_plans_nothing() -> None:
    assert ClaudeCodeAdapter().plan_config({}, {}, {}) == []


# --- diagnostics ----------------------------------------------------------


def test_preserved_reports_foreign_hook_entries() -> None:
    cfg = _cfg_with_profile(Path("/nonexistent"))
    existing = json.dumps(
        {
            "hooks": {
                "Stop": [
                    {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": "/usr/local/bin/theirs"}],
                    }
                ]
            }
        },
        indent=2,
    )

    ops = ClaudeCodeAdapter().plan_config(
        _entries_for(cfg, PROFILE, "lh"), {}, {SETTINGS: existing}
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None
    assert any("/usr/local/bin/theirs" in line and "Stop" in line for line in op.preserved)
    assert op.repaired == []


def test_repaired_reports_entries_claude_code_would_reject() -> None:
    cfg = _cfg_with_profile(Path("/nonexistent"))
    existing = json.dumps(
        {
            "hooks": {
                "Stop": [
                    {
                        "matcher": None,
                        "hooks": [{"type": "command", "command": "/usr/local/bin/theirs"}],
                    }
                ]
            }
        },
        indent=2,
    )

    ops = ClaudeCodeAdapter().plan_config(
        _entries_for(cfg, PROFILE, "lh"), {}, {SETTINGS: existing}
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None
    assert any("matcher" in line for line in op.repaired)
    assert op.artifact is not None
    merged = json.loads(op.artifact.content)
    matchers = [e["matcher"] for e in merged["hooks"]["Stop"]]
    assert None not in matchers


def test_dropped_reports_harness_entries_no_longer_generated() -> None:
    """A builtin removed from a release leaves its command behind in every
    deployed settings.json. It is pruned — silently today — and the plan says so."""
    cfg = _cfg_with_profile(Path("/nonexistent"))
    existing = json.dumps(
        {
            "hooks": {
                "Stop": [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "lh hook retired_hook --profile personal",
                            }
                        ],
                    }
                ]
            }
        },
        indent=2,
    )

    ops = ClaudeCodeAdapter().plan_config(
        _entries_for(cfg, PROFILE, "lh"), {}, {SETTINGS: existing}
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None
    assert any("retired_hook" in line for line in op.dropped)
    assert not any("retired_hook" in line for line in op.preserved)
    assert op.artifact is not None
    assert "retired_hook" not in op.artifact.content


def test_preserved_reports_foreign_mcp_servers() -> None:
    existing = json.dumps({"mcpServers": {"someone-elses": {"command": "other"}}}, indent=2)

    ops = ClaudeCodeAdapter().plan_config({}, MCP_SERVERS, {CLAUDE_JSON: existing})

    op = _op_for(ops, CLAUDE_JSON)
    assert op is not None
    assert any("someone-elses" in line for line in op.preserved)


def test_mcp_plan_survives_a_document_that_is_not_an_object() -> None:
    """`deploy_mcp_servers` raises `AttributeError` here; a planner that cannot
    be handed a bad file is a planner the engine has to guard around."""
    ops = ClaudeCodeAdapter().plan_config({}, MCP_SERVERS, {CLAUDE_JSON: "[1, 2, 3]"})

    op = _op_for(ops, CLAUDE_JSON)
    assert op is not None and op.artifact is not None
    assert json.loads(op.artifact.content)["mcpServers"]["qmd"]["command"] == "qmd"
