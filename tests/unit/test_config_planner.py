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

from lazy_harness.agents._settings_shape import fatal_hook_shape
from lazy_harness.agents.base import ConfigPlanner, HookEntry, HookOwnership
from lazy_harness.agents.claude_code import ClaudeCodeAdapter, SettingsShapeError
from lazy_harness.core.config import (
    Config,
    ExternalHookConfig,
    HarnessConfig,
    HookEventConfig,
    ProfileEntry,
    ProfilesConfig,
)

SETTINGS = Path("settings.json")
OWNERSHIP = Path("lh-hook-ownership.json")
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
                HookEntry(
                    command=ext.command,
                    matcher=ext.matcher,
                    ownership=HookOwnership.EXTERNAL,
                )
            )
    return entries


def _op_for(ops: list, path: Path):
    matching = [op for op in ops if op.relative_path == path]
    assert len(matching) <= 1, f"{path} planned more than once: {len(matching)} ops"
    return matching[0] if matching else None


def _redeploy_over(ops: list) -> dict[Path, str]:
    """The `existing` a second `plan_config` call would see, carrying every
    file the first call wrote forward — the settings.json and its ownership
    sidecar are two separate reads/writes now, and a test simulating a second
    deploy must thread both or the sidecar looks like it was never written."""
    return {op.relative_path: op.artifact.content for op in ops if op.artifact is not None}


# --- the protocol itself -------------------------------------------------


def test_adapter_satisfies_config_planner_protocol() -> None:
    assert isinstance(ClaudeCodeAdapter(), ConfigPlanner)


def test_config_targets_names_settings_the_ownership_ledger_and_the_mcp_file() -> None:
    adapter = ClaudeCodeAdapter()
    targets = adapter.config_targets()

    assert targets == [SETTINGS, OWNERSHIP, Path(adapter.mcp_config_file())]
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
    """Foreign entries, a repairable one, an invented builtin-shaped command,
    an unmodelled event and unrelated top-level keys survive byte-identically."""
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
                        {
                            "type": "command",
                            "command": "lh hook definitely-not-a-builtin --profile personal",
                        }
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


def test_settings_serialization_keeps_non_ascii_text_literal() -> None:
    existing = json.dumps({"note": "ejecución — activa", "hooks": {}}, indent=2, ensure_ascii=False)

    ops = ClaudeCodeAdapter().plan_config(
        {"session_start": [HookEntry(command="lh hook context-inject --profile personal")]},
        {},
        {SETTINGS: existing},
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert "ejecución — activa" in op.artifact.content
    assert "\\u00f3" not in op.artifact.content
    assert "\\u2014" not in op.artifact.content


def test_claude_json_serialization_keeps_non_ascii_text_literal() -> None:
    existing = json.dumps({"note": "ejecución — activa"}, indent=2, ensure_ascii=False)

    ops = ClaudeCodeAdapter().plan_config({}, MCP_SERVERS, {CLAUDE_JSON: existing})

    op = _op_for(ops, CLAUDE_JSON)
    assert op is not None and op.artifact is not None
    assert "ejecución — activa" in op.artifact.content
    assert "\\u00f3" not in op.artifact.content
    assert "\\u2014" not in op.artifact.content


def test_both_targets_planned_in_one_call(tmp_path: Path) -> None:
    cfg = _cfg_with_profile(tmp_path / "profile")

    ops = ClaudeCodeAdapter().plan_config(_entries_for(cfg, PROFILE, "lh"), MCP_SERVERS, {})

    assert [op.relative_path for op in ops] == [SETTINGS, OWNERSHIP, CLAUDE_JSON]


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


def test_external_equivalent_keeps_richer_native_claude_metadata() -> None:
    richer = {
        "matcher": "Write",
        "hooks": [
            {
                "type": "command",
                "command": "other-tool guard",
                "timeout": 45,
                "async": True,
            }
        ],
    }
    existing = json.dumps({"hooks": {"PreToolUse": [richer]}}, indent=2)
    desired = {
        "pre_tool_use": [
            HookEntry(
                command="other-tool guard",
                matcher="Write",
                ownership=HookOwnership.EXTERNAL,
            )
        ]
    }

    ops = ClaudeCodeAdapter().plan_config(desired, {}, {SETTINGS: existing}, binary="lh")

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert json.loads(op.artifact.content)["hooks"]["PreToolUse"] == [richer]
    assert op.dropped == []


def test_claude_external_identity_includes_matcher_and_keeps_foreign_duplicates() -> None:
    bash = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "other-tool guard"}],
    }
    existing = json.dumps({"hooks": {"PreToolUse": [bash, bash]}}, indent=2)
    desired = {
        "pre_tool_use": [
            HookEntry(
                command="other-tool guard",
                matcher="Write",
                ownership=HookOwnership.EXTERNAL,
            )
        ]
    }

    ops = ClaudeCodeAdapter().plan_config(desired, {}, {SETTINGS: existing}, binary="lh")

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert json.loads(op.artifact.content)["hooks"]["PreToolUse"] == [
        {
            "matcher": "Write",
            "hooks": [{"type": "command", "command": "other-tool guard"}],
        },
        bash,
        bash,
    ]


def test_claude_equivalent_external_keeps_all_foreign_duplicates_and_metadata() -> None:
    first_foreign = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "other-tool session", "timeout": 10}],
    }
    second_foreign = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "other-tool session", "timeout": 45}],
    }
    desired = {
        "session_start": [HookEntry(command="other-tool session", ownership=HookOwnership.EXTERNAL)]
    }
    existing = json.dumps({"hooks": {"SessionStart": [first_foreign, second_foreign]}}, indent=2)

    first = ClaudeCodeAdapter().plan_config(desired, {}, {SETTINGS: existing}, binary="lh")
    first_op = _op_for(first, SETTINGS)
    assert first_op is not None and first_op.artifact is not None
    assert json.loads(first_op.artifact.content)["hooks"]["SessionStart"] == [
        first_foreign,
        second_foreign,
    ]

    second = ClaudeCodeAdapter().plan_config(
        desired, {}, {SETTINGS: first_op.artifact.content}, binary="lh"
    )
    second_op = _op_for(second, SETTINGS)
    assert second_op is not None and second_op.artifact is not None
    assert json.loads(second_op.artifact.content)["hooks"]["SessionStart"] == [
        first_foreign,
        second_foreign,
    ]


def test_claude_null_ownership_cannot_adopt_an_external_builtin_on_omission() -> None:
    desired = {
        "session_start": [
            HookEntry(
                command="lh hook context-inject --profile p",
                ownership=HookOwnership.EXTERNAL,
            )
        ]
    }
    first = ClaudeCodeAdapter().plan_config(desired, {}, {}, binary="lh")
    first_settings = _op_for(first, SETTINGS)
    assert first_settings is not None and first_settings.artifact is not None

    omitted = ClaudeCodeAdapter().plan_config(
        {},
        {},
        {SETTINGS: first_settings.artifact.content, OWNERSHIP: "null"},
        binary="lh",
    )

    assert _op_for(omitted, SETTINGS) is None


@pytest.mark.parametrize("envelope", [None, {}, [], 1])
def test_claude_present_invalid_ownership_never_enables_legacy_adoption(
    envelope: object,
) -> None:
    group = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}],
    }
    existing = json.dumps({"hooks": {"SessionStart": [group]}})

    assert (
        ClaudeCodeAdapter().plan_config(
            {}, {}, {SETTINGS: existing, OWNERSHIP: json.dumps(envelope)}, binary="lh"
        )
        == []
    )


@pytest.mark.parametrize("version", [True, 1.0, False, None, 2, "1"])
def test_claude_non_integer_version_cannot_authorize_an_exact_recorded_group(
    version: object,
) -> None:
    group = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}],
    }
    envelope = {
        "version": version,
        "managed": [{"event": "SessionStart", "index": 0, "group": group}],
    }
    existing = json.dumps({"hooks": {"SessionStart": [group]}})

    assert (
        ClaudeCodeAdapter().plan_config(
            {}, {}, {SETTINGS: existing, OWNERSHIP: json.dumps(envelope)}, binary="lh"
        )
        == []
    )


def test_claude_absent_ownership_still_enables_exact_legacy_migration() -> None:
    group = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}],
    }
    existing = json.dumps({"hooks": {"SessionStart": [group]}})

    ops = ClaudeCodeAdapter().plan_config({}, {}, {SETTINGS: existing}, binary="lh")

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert json.loads(op.artifact.content)["hooks"] == {}


def test_claude_settings_json_ledger_migrates_to_the_sidecar_once() -> None:
    """A `lh_hook_ownership` key still embedded in settings.json — what a pre-fix
    deploy wrote — is read once as this deploy's ledger, moved to the sidecar,
    and never appears back in settings.json: that key shape is what Claude Code
    2.1.278 classifies as a fatal settings error and discards the whole file
    for."""
    managed_group = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}],
    }
    stale_group = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "lh hook retired-hook --profile p"}],
    }
    legacy_envelope = {
        "version": 1,
        "managed": [
            {"event": "SessionStart", "index": 0, "group": managed_group},
            {"event": "SessionStart", "index": 1, "group": stale_group},
        ],
    }
    existing = json.dumps(
        {
            "hooks": {"SessionStart": [managed_group, stale_group]},
            "lh_hook_ownership": legacy_envelope,
        }
    )
    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}

    ops = ClaudeCodeAdapter().plan_config(desired, {}, {SETTINGS: existing}, binary="lh")

    settings_op = _op_for(ops, SETTINGS)
    assert settings_op is not None and settings_op.artifact is not None
    written_settings = json.loads(settings_op.artifact.content)
    assert "lh_hook_ownership" not in written_settings
    assert written_settings["hooks"]["SessionStart"] == [managed_group]

    ownership_op = _op_for(ops, OWNERSHIP)
    assert ownership_op is not None and ownership_op.artifact is not None
    assert json.loads(ownership_op.artifact.content) == {
        "version": 1,
        "managed": [{"event": "SessionStart", "index": 0, "group": managed_group}],
    }


# --- ownership by identity, not position ----------------------------------


def test_claude_foreign_entry_inserted_before_ours_does_not_duplicate_the_block() -> None:
    """An external tool that inserts an entry earlier in the same event's list
    shifts every index after it. The ledger's recorded index still points at
    the old position, which now holds the foreign entry, not ours — claiming
    must fall back to scanning by identity instead of giving up."""
    managed_group = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}],
    }
    foreign = {"matcher": "", "hooks": [{"type": "command", "command": "other-tool session"}]}
    envelope = {
        "version": 1,
        "managed": [{"event": "SessionStart", "index": 0, "group": managed_group}],
    }
    shifted = json.dumps({"hooks": {"SessionStart": [foreign, managed_group]}})
    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}

    ops = ClaudeCodeAdapter().plan_config(
        desired, {}, {SETTINGS: shifted, OWNERSHIP: json.dumps(envelope)}, binary="lh"
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    entries = json.loads(op.artifact.content)["hooks"]["SessionStart"]
    assert entries == [managed_group, foreign]


def test_claude_foreign_entry_deleted_from_before_ours_does_not_duplicate_the_block() -> None:
    """The same shift in the other direction: deleting an earlier foreign entry
    pulls ours down an index. The recorded index (1) is now out of range for a
    one-entry list, which used to mean "not owned" and therefore duplicated."""
    managed_group = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}],
    }
    envelope = {
        "version": 1,
        "managed": [{"event": "SessionStart", "index": 1, "group": managed_group}],
    }
    shifted = json.dumps({"hooks": {"SessionStart": [managed_group]}})
    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}

    ops = ClaudeCodeAdapter().plan_config(
        desired, {}, {SETTINGS: shifted, OWNERSHIP: json.dumps(envelope)}, binary="lh"
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert json.loads(op.artifact.content)["hooks"]["SessionStart"] == [managed_group]


def test_claude_entry_edited_outside_identity_is_still_claimed() -> None:
    """A foreign edit to a field the identity does not cover — a `timeout`, say
    — is still our entry: the harness regenerates it anyway, so exact byte
    equality against the recorded group would only cause a spurious duplicate."""
    managed_group = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}],
    }
    edited = {
        "matcher": "",
        "hooks": [
            {"type": "command", "command": "lh hook context-inject --profile p", "timeout": 30}
        ],
    }
    envelope = {
        "version": 1,
        "managed": [{"event": "SessionStart", "index": 0, "group": managed_group}],
    }
    existing = json.dumps({"hooks": {"SessionStart": [edited]}})
    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}

    ops = ClaudeCodeAdapter().plan_config(
        desired, {}, {SETTINGS: existing, OWNERSHIP: json.dumps(envelope)}, binary="lh"
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert json.loads(op.artifact.content)["hooks"]["SessionStart"] == [managed_group]


def test_claude_duplicate_identity_with_one_ledger_record_claims_exactly_one() -> None:
    """Two entries share an identity but only one ledger record exists: the scan
    must claim exactly one of them, leaving the other as a genuine foreign
    duplicate rather than adopting both or neither."""
    managed_group = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}],
    }
    envelope = {
        "version": 1,
        "managed": [{"event": "SessionStart", "index": 0, "group": managed_group}],
    }
    existing = json.dumps({"hooks": {"SessionStart": [managed_group, managed_group]}})
    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}

    ops = ClaudeCodeAdapter().plan_config(
        desired, {}, {SETTINGS: existing, OWNERSHIP: json.dumps(envelope)}, binary="lh"
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert json.loads(op.artifact.content)["hooks"]["SessionStart"] == [
        managed_group,
        managed_group,
    ]


def test_claude_malformed_ledger_group_claims_nothing_without_crashing() -> None:
    """A ledger record whose stored group has no computable identity (here, a
    non-string matcher) must not crash the merge — it simply claims nothing,
    and the entry it describes is carried through like any other foreign one.

    Desired hooks must be non-empty here: with nothing desired and nothing
    claimed there is genuinely no work, and `plan_config` leaves the file
    untouched rather than rewriting it — a different, already-covered case."""
    malformed_group = {
        "matcher": [],
        "hooks": [{"type": "command", "command": "other-tool session"}],
    }
    envelope = {
        "version": 1,
        "managed": [{"event": "SessionStart", "index": 0, "group": malformed_group}],
    }
    existing = json.dumps({"hooks": {"SessionStart": [malformed_group]}})
    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}

    ops = ClaudeCodeAdapter().plan_config(
        desired, {}, {SETTINGS: existing, OWNERSHIP: json.dumps(envelope)}, binary="lh"
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    entries = json.loads(op.artifact.content)["hooks"]["SessionStart"]
    assert len(entries) == 2
    preserved = entries[-1]
    assert preserved["hooks"] == malformed_group["hooks"]
    assert preserved["matcher"] == ""


def test_claude_shifted_lineages_redeploy_produces_no_duplicate() -> None:
    """The regression that started this: `settings.json` and the ownership
    ledger come from different lineages (a symlink restoration merged two
    histories of the same block), so every recorded index points at a position
    that has since shifted. A redeploy must not duplicate any managed group."""
    desired = {
        "session_start": [
            HookEntry(command="lh hook context-inject --profile p"),
            HookEntry(command="lh hook session-start-preflight --profile p"),
        ]
    }
    canonical = ClaudeCodeAdapter().plan_config(desired, {}, {}, binary="lh")
    canonical_op = _op_for(canonical, SETTINGS)
    assert canonical_op is not None and canonical_op.artifact is not None
    group_1, group_2 = json.loads(canonical_op.artifact.content)["hooks"]["SessionStart"]

    foreign_a = {"matcher": "", "hooks": [{"type": "command", "command": "other-tool a"}]}
    foreign_b = {"matcher": "", "hooks": [{"type": "command", "command": "other-tool b"}]}
    envelope = {
        "version": 1,
        "managed": [
            {"event": "SessionStart", "index": 0, "group": group_1},
            {"event": "SessionStart", "index": 1, "group": group_2},
        ],
    }
    shifted = json.dumps({"hooks": {"SessionStart": [foreign_a, group_1, foreign_b, group_2]}})

    ops = ClaudeCodeAdapter().plan_config(
        desired, {}, {SETTINGS: shifted, OWNERSHIP: json.dumps(envelope)}, binary="lh"
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert json.loads(op.artifact.content)["hooks"]["SessionStart"] == [
        group_1,
        group_2,
        foreign_a,
        foreign_b,
    ]


def test_claude_preserves_prompt_only_and_mixed_foreign_groups() -> None:
    prompt = {"matcher": "", "hooks": [{"type": "prompt", "prompt": "review it"}]}
    mixed = {
        "matcher": "",
        "hooks": [
            {"type": "command", "command": "lh hook context-inject --profile p"},
            {"type": "prompt", "prompt": "also review it"},
        ],
    }
    existing = json.dumps({"hooks": {"SessionStart": [prompt, mixed]}}, indent=2)
    desired = {"session_start": [HookEntry(command="lh hook session-start-preflight --profile p")]}

    ops = ClaudeCodeAdapter().plan_config(desired, {}, {SETTINGS: existing}, binary="lh")

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert json.loads(op.artifact.content)["hooks"]["SessionStart"][-2:] == [prompt, mixed]


def test_claude_external_builtin_text_never_transfers_lifecycle_ownership() -> None:
    first_desired = {
        "session_start": [
            HookEntry(
                command="lh hook context-inject --profile other",
                ownership=HookOwnership.EXTERNAL,
            ),
            HookEntry(command="lh hook session-start-preflight --profile p"),
        ]
    }
    first = ClaudeCodeAdapter().plan_config(first_desired, {}, {}, binary="lh")
    first_op = _op_for(first, SETTINGS)
    assert first_op is not None and first_op.artifact is not None

    second = ClaudeCodeAdapter().plan_config(
        {"session_start": [HookEntry(command="lh hook session-start-preflight --profile p")]},
        {},
        _redeploy_over(first),
        binary="lh",
    )

    second_op = _op_for(second, SETTINGS)
    assert second_op is not None and second_op.artifact is not None
    commands = [
        group["hooks"][0]["command"]
        for group in json.loads(second_op.artifact.content)["hooks"]["SessionStart"]
    ]
    assert commands.count("lh hook context-inject --profile other") == 1
    assert commands.count("lh hook session-start-preflight --profile p") == 1


def test_claude_external_only_builtin_text_survives_omission() -> None:
    desired = {
        "session_start": [
            HookEntry(
                command="lh hook context-inject --profile other",
                ownership=HookOwnership.EXTERNAL,
            )
        ]
    }
    first = ClaudeCodeAdapter().plan_config(desired, {}, {}, binary="lh")
    first_op = _op_for(first, SETTINGS)
    assert first_op is not None and first_op.artifact is not None

    second = ClaudeCodeAdapter().plan_config({}, {}, _redeploy_over(first), binary="lh")

    assert _op_for(second, SETTINGS) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("matcher", []),
        ("type", {}),
        ("command", []),
        ("command", None),
    ],
)
def test_claude_invalid_identity_fields_are_preserved_without_traceback(
    field: str, value: object
) -> None:
    malformed = {
        "matcher": "",
        "hooks": [
            {"type": "command", "command": "other-tool session"},
            {"type": "prompt", "command": "ignored"},
        ],
    }
    if field == "matcher":
        malformed[field] = value
    else:
        malformed["hooks"][1][field] = value
    existing = json.dumps({"hooks": {"SessionStart": [malformed]}}, indent=2)

    ops = ClaudeCodeAdapter().plan_config(
        {"session_start": [HookEntry(command="lh hook context-inject --profile p")]},
        {},
        {SETTINGS: existing},
        binary="lh",
    )

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    preserved = json.loads(op.artifact.content)["hooks"]["SessionStart"][-1]
    assert preserved["hooks"] == malformed["hooks"]
    assert preserved["matcher"] == ("" if field == "matcher" else malformed["matcher"])


def test_claude_can_retire_the_last_recorded_builtin() -> None:
    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}
    first = ClaudeCodeAdapter().plan_config(desired, {}, {}, binary="lh")
    first_op = _op_for(first, SETTINGS)
    assert first_op is not None and first_op.artifact is not None

    second = ClaudeCodeAdapter().plan_config({}, {}, _redeploy_over(first), binary="lh")

    second_op = _op_for(second, SETTINGS)
    assert second_op is not None and second_op.artifact is not None
    assert json.loads(second_op.artifact.content)["hooks"] == {}


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
    """A registered migration alias is still recognizable and retireable."""
    cfg = _cfg_with_profile(Path("/nonexistent"))
    existing = json.dumps(
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Edit|Write",
                        "hooks": [
                            {
                                "type": "command",
                                "command": ("lh hook post-tool-use-sync-claude --profile personal"),
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
    assert any("post-tool-use-sync-claude" in line for line in op.dropped)
    assert not any("post-tool-use-sync-claude" in line for line in op.preserved)
    assert op.artifact is not None
    assert "post-tool-use-sync-claude" not in op.artifact.content


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


# --- the fatal-shape gate ------------------------------------------------


def test_claude_refuses_to_write_settings_the_agent_would_discard_whole() -> None:
    """The gate the `lh_hook_ownership` incident asked for. A foreign top-level
    key shaped like a hook declaration makes Claude Code 2.1.278 throw away the
    entire settings file — no hooks, no permissions, no env. `plan_config`
    copies every top-level key it does not own into the artifact, so without
    this check `lh deploy` writes that file and exits 0."""
    existing = json.dumps(
        {
            "hooks": {},
            "herdr_integration": {
                "installed": [
                    {"matcher": "", "hooks": [{"type": "command", "command": "herdr hook"}]}
                ]
            },
        }
    )
    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}

    with pytest.raises(SettingsShapeError) as excinfo:
        ClaudeCodeAdapter().plan_config(desired, {}, {SETTINGS: existing}, binary="lh")

    assert "$.herdr_integration.installed[0]" in str(excinfo.value)


def test_claude_gate_reads_the_document_it_is_about_to_write_not_the_one_it_read() -> None:
    """The distinction that failed during the incident: an input that is clean
    is not a guarantee about the output. The legacy in-settings ledger is popped
    by the migration, so the same bytes that were fatal on disk plan cleanly —
    and the gate must agree, or every migrating profile is blocked."""
    group = {
        "matcher": "",
        "hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}],
    }
    existing = json.dumps(
        {
            "hooks": {"SessionStart": [group]},
            "lh_hook_ownership": {
                "version": 1,
                "managed": [{"event": "SessionStart", "index": 0, "group": group}],
            },
        }
    )
    assert fatal_hook_shape(json.loads(existing)) == "$.lh_hook_ownership.managed[0].group"

    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}
    ops = ClaudeCodeAdapter().plan_config(desired, {}, {SETTINGS: existing}, binary="lh")

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert fatal_hook_shape(json.loads(op.artifact.content)) is None


def test_claude_gate_leaves_an_ordinary_foreign_top_level_key_alone() -> None:
    """Preservation is the rule; the gate is the exception. A top-level key that
    is not hook-shaped must still be copied through untouched."""
    existing = json.dumps({"hooks": {}, "statusLine": {"type": "command", "command": "lh status"}})
    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}

    ops = ClaudeCodeAdapter().plan_config(desired, {}, {SETTINGS: existing}, binary="lh")

    op = _op_for(ops, SETTINGS)
    assert op is not None and op.artifact is not None
    assert json.loads(op.artifact.content)["statusLine"] == {
        "type": "command",
        "command": "lh status",
    }


def test_claude_gate_does_not_exempt_a_key_for_looking_like_the_harness_s_own() -> None:
    """`lh_hook_ownership` was the harness's own key, not a foreign tool's, and
    it was exactly as fatal. Nothing in the gate special-cases a key for being
    namespaced like the harness: if a future feature ever stores a hook group
    under a new top-level key, it must be refused the same way."""
    existing = json.dumps(
        {
            "hooks": {},
            "lh_debug_last_hook_group": {
                "matcher": "",
                "hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}],
            },
        }
    )
    desired = {"session_start": [HookEntry(command="lh hook context-inject --profile p")]}

    with pytest.raises(SettingsShapeError) as excinfo:
        ClaudeCodeAdapter().plan_config(desired, {}, {SETTINGS: existing}, binary="lh")

    assert "$.lh_debug_last_hook_group" in str(excinfo.value)


def test_claude_gate_does_not_run_when_the_plan_writes_nothing() -> None:
    """`_plan_settings` returns `(None, None)` before the gate runs whenever
    there is nothing to deploy — no desired hooks and nothing previously owned.
    A foreign fatal key already on disk must not turn that no-op into a raise:
    a file the plan never writes is a file the gate has no business judging."""
    existing = json.dumps(
        {
            "hooks": {},
            "herdr_integration": {
                "installed": [
                    {"matcher": "", "hooks": [{"type": "command", "command": "herdr hook"}]}
                ]
            },
        }
    )

    ops = ClaudeCodeAdapter().plan_config({}, {}, {SETTINGS: existing}, binary="lh")

    assert _op_for(ops, SETTINGS) is None
