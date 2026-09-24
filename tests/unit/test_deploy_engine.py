"""Tests for deploy_hooks — engine-level integration with merge_with_defaults."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from lazy_harness.agents.base import HookOwnership
from lazy_harness.core.config import (
    Config,
    ExternalHookConfig,
    HarnessConfig,
    HookEventConfig,
    ProfileEntry,
    ProfilesConfig,
)
from lazy_harness.deploy.engine import deploy_hooks

# `_is_harness_owned` takes the owned-launcher set from the artifact being
# merged, so it has no default; these cases are about a stock `lh` install.
DEFAULT_BINARIES = {"lh"}


def _cfg_with_profile(profile_dir: Path, hooks: dict[str, HookEventConfig] | None = None) -> Config:
    """Build a minimal Config pointing one profile at `profile_dir`."""
    return Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={"personal": ProfileEntry(config_dir=str(profile_dir), roots=["~"])},
        ),
        hooks=hooks or {},
    )


def test_deploy_hooks_fresh_profile_writes_all_defaults(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    cc_hooks = settings["hooks"]
    for cc_event in (
        "SessionStart",
        "Stop",
        "SessionEnd",
        "PreCompact",
        "PreToolUse",
        "PostToolUse",
    ):
        assert cc_event in cc_hooks, f"missing {cc_event} in deployed hooks"
    assert "PostCompact" not in cc_hooks, (
        "the PostCompact event has no channel to the model; deploying a hook "
        "there wires a command that can only print to the user"
    )


def test_deploy_hooks_idempotent_on_clean_managed_state(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)
    first = (profile_dir / "settings.json").read_text()

    deploy_hooks(cfg)
    second = (profile_dir / "settings.json").read_text()

    assert first == second
    assert not (profile_dir / "settings.json.bak").exists()


def test_deploy_hooks_preserves_foreign_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A hook the harness did not generate belongs to some other tool. Deploying
    a harness hook must not uninstall it."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    pre = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "/usr/local/bin/my-manual-hook"}],
                }
            ]
        }
    }
    (profile_dir / "settings.json").write_text(json.dumps(pre, indent=2) + "\n")
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)

    new = json.loads((profile_dir / "settings.json").read_text())
    assert "my-manual-hook" in json.dumps(new["hooks"]["Stop"])
    assert any(
        "session-export" in json.dumps(e) or "compound-loop" in json.dumps(e)
        for e in new["hooks"]["Stop"]
    ), "harness hooks should still deploy alongside"

    out = capsys.readouterr().out
    assert "my-manual-hook" in out, "preserving silently is still a surprise; say it"


def test_deploy_hooks_preserves_foreign_entries_on_unmodelled_events(tmp_path: Path) -> None:
    """The harness has no concept of some events. It must pass them through
    rather than delete what it cannot model."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    pre = {
        "hooks": {
            "SomeFutureEvent": [
                {"matcher": "", "hooks": [{"type": "command", "command": "/bin/other-tool"}]}
            ]
        }
    }
    (profile_dir / "settings.json").write_text(json.dumps(pre, indent=2) + "\n")
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)

    new = json.loads((profile_dir / "settings.json").read_text())
    assert "/bin/other-tool" in json.dumps(new["hooks"].get("SomeFutureEvent", []))


def test_deploy_hooks_counts_every_preserved_entry_not_unique_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression for the 9x undercount: one command registered on three events
    is three entries, not one."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    entry = {"matcher": "", "hooks": [{"type": "command", "command": "/bin/notifier hook"}]}
    pre = {"hooks": {"Stop": [entry], "SessionEnd": [entry], "SomeFutureEvent": [entry]}}
    (profile_dir / "settings.json").write_text(json.dumps(pre, indent=2) + "\n")
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)

    out = capsys.readouterr().out
    assert "3" in out, f"expected a count of 3 preserved entries, got: {out}"
    assert out.count("/bin/notifier hook") == 3, "each entry reported with its event"


def test_deploy_hooks_normalizes_null_matcher_and_reports_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A null matcher makes Claude Code discard the entire settings file. Fix it
    on sight, and say so — never silently."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    pre = {
        "hooks": {
            "SomeFutureEvent": [
                {"matcher": None, "hooks": [{"type": "command", "command": "/bin/other-tool"}]}
            ]
        }
    }
    (profile_dir / "settings.json").write_text(json.dumps(pre, indent=2) + "\n")
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)

    new = json.loads((profile_dir / "settings.json").read_text())
    assert new["hooks"]["SomeFutureEvent"][0]["matcher"] == ""

    out = capsys.readouterr().out.lower()
    assert "normal" in out or "repair" in out or "fixed" in out, "the repair must be announced"


def test_deploy_hooks_emits_declared_external_commands(tmp_path: Path) -> None:
    """External hooks declared in config reach the profile with a valid matcher."""
    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(
        profile_dir,
        hooks={
            "user_prompt_submit": HookEventConfig(
                scripts=[], external=[ExternalHookConfig(command="/bin/notifier hook")]
            ),
            "pre_tool_use": HookEventConfig(
                scripts=["pre-tool-use-security"],
                external=[
                    ExternalHookConfig(command="/bin/notifier hook", matcher="AskUserQuestion")
                ],
            ),
        },
    )

    deploy_hooks(cfg)

    cc_hooks = json.loads((profile_dir / "settings.json").read_text())["hooks"]
    ups = cc_hooks["UserPromptSubmit"]
    assert ups[0]["hooks"][0]["command"] == "/bin/notifier hook"
    assert ups[0]["matcher"] == ""
    pinned = [e for e in cc_hooks["PreToolUse"] if e["matcher"] == "AskUserQuestion"]
    assert len(pinned) == 1
    assert pinned[0]["hooks"][0]["command"] == "/bin/notifier hook"


def test_engine_marks_builtins_managed_and_external_entries_foreign(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    cfg = _cfg_with_profile(
        tmp_path / "profile",
        hooks={
            "session_start": HookEventConfig(
                scripts=["context-inject"],
                external=[ExternalHookConfig(command="other-tool session")],
            )
        },
    )

    entries = _hook_entries_for(cfg, "personal", "lh")["session_start"]

    assert entries[0].ownership is HookOwnership.HARNESS
    assert entries[-1].ownership is HookOwnership.EXTERNAL


def test_codex_user_script_converges_and_omission_preserves_it(home_dir: Path) -> None:
    """A resolved user script is ensure-present, not a builtin owned by lh."""
    hooks_dir = home_dir / ".config" / "lazy-harness" / "hooks"
    hooks_dir.mkdir(parents=True)
    script = hooks_dir / "custom.py"
    script.write_text("print('custom')\n")
    profile_dir = home_dir / ".codex-probe"
    cfg = _cfg_with_profile(
        profile_dir,
        hooks={"session_start": HookEventConfig(scripts=["custom"])},
    )
    cfg.profiles.items["personal"].agent = "codex"

    deploy_hooks(cfg)
    first = (profile_dir / "hooks.json").read_text()
    deploy_hooks(cfg)
    second = (profile_dir / "hooks.json").read_text()

    assert second == first
    groups = json.loads(second)["hooks"]["SessionStart"]
    command = f"{sys.executable} {script}"
    assert [group["hooks"][0]["command"] for group in groups].count(command) == 1

    cfg.hooks["session_start"].scripts = []
    deploy_hooks(cfg)

    after_omission = json.loads((profile_dir / "hooks.json").read_text())
    assert any(
        group["hooks"][0]["command"] == command for group in after_omission["hooks"]["SessionStart"]
    )


def test_codex_deploy_preserves_foreign_hooks_and_is_byte_stable(tmp_path: Path) -> None:
    profile_dir = tmp_path / "codex-profile"
    profile_dir.mkdir()
    foreign = {
        "matcher": "startup",
        "hooks": [
            {
                "type": "command",
                "command": "other-tool session",
                "timeoutSec": 45,
            }
        ],
    }
    hooks_file = profile_dir / "hooks.json"
    hooks_file.write_text(json.dumps({"hooks": {"SessionStart": [foreign]}}, indent=2))
    cfg = _cfg_with_profile(profile_dir)
    cfg.profiles.items["personal"].agent = "codex"

    deploy_hooks(cfg)
    first = hooks_file.read_text()
    deploy_hooks(cfg)
    second = hooks_file.read_text()

    assert json.loads(first)["hooks"]["SessionStart"][0] == foreign
    assert second == first


def test_deploy_hooks_expands_config_dir_placeholder_per_profile(tmp_path: Path) -> None:
    """ADR-054: an external command naming `{config_dir}` resolves to each
    profile's own directory, not one fixed string shared by every profile."""
    from lazy_harness.deploy.engine import _hook_entries_for

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir="~/.claude-lazy"),
                "flex": ProfileEntry(config_dir="~/.claude-flex"),
            },
        ),
        hooks={
            "session_start": HookEventConfig(
                external=[
                    ExternalHookConfig(
                        command="bash {config_dir}/hooks/herdr-agent-state.sh session"
                    )
                ]
            )
        },
    )

    lazy_entries = _hook_entries_for(cfg, "lazy", "lh")
    flex_entries = _hook_entries_for(cfg, "flex", "lh")

    lazy_command = lazy_entries["session_start"][0].command
    flex_command = flex_entries["session_start"][0].command
    assert lazy_command == "bash ~/.claude-lazy/hooks/herdr-agent-state.sh session"
    assert flex_command == "bash ~/.claude-flex/hooks/herdr-agent-state.sh session"


def test_deploy_hooks_config_dir_placeholder_stays_unexpanded(tmp_path: Path) -> None:
    """`{config_dir}` is the raw config field, tilde and all — never the
    resolved absolute path, for the same chezmoi-portability reason
    `hook_command` never embeds a home directory."""
    from lazy_harness.deploy.engine import _hook_entries_for

    cfg = _cfg_with_profile(
        tmp_path / "profile",
        hooks={
            "session_start": HookEventConfig(
                external=[ExternalHookConfig(command="cat {config_dir}/marker")]
            )
        },
    )
    cfg.profiles.items["personal"].config_dir = "~/.claude-personal"

    entries = _hook_entries_for(cfg, "personal", "lh")

    assert entries["session_start"][0].command == "cat ~/.claude-personal/marker"


def test_deploy_hooks_expands_profile_placeholder(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    cfg = _cfg_with_profile(
        tmp_path / "profile",
        hooks={
            "session_start": HookEventConfig(
                external=[ExternalHookConfig(command="notify --profile {profile}")]
            )
        },
    )

    entries = _hook_entries_for(cfg, "personal", "lh")

    assert entries["session_start"][0].command == "notify --profile personal"


def test_deploy_hooks_plain_external_command_is_unchanged_by_expansion(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    cfg = _cfg_with_profile(
        tmp_path / "profile",
        hooks={
            "session_start": HookEventConfig(
                external=[ExternalHookConfig(command="/bin/notifier hook")]
            )
        },
    )

    entries = _hook_entries_for(cfg, "personal", "lh")

    assert entries["session_start"][0].command == "/bin/notifier hook"


def test_deploy_hooks_escaped_braces_are_literal(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    command = 'echo ${{HOME}} && awk "{{print $1}}" && notify {profile}'
    cfg = _cfg_with_profile(
        tmp_path / "profile",
        hooks={"session_start": HookEventConfig(external=[ExternalHookConfig(command=command)])},
    )

    entries = _hook_entries_for(cfg, "personal", "lh")

    assert entries["session_start"][0].command == (
        'echo ${HOME} && awk "{print $1}" && notify personal'
    )


@pytest.mark.parametrize(
    ("command", "field"),
    [
        ("notify {", "{"),
        ("notify {profile!z}", "{profile!z}"),
        ("notify {profile.x}", "{profile.x}"),
    ],
)
def test_deploy_hooks_malformed_placeholder_is_refused_with_diagnostic(
    tmp_path: Path, command: str, field: str
) -> None:
    from lazy_harness.deploy.engine import ExternalHookPlaceholderError, _hook_entries_for

    cfg = _cfg_with_profile(
        tmp_path / "profile",
        hooks={"session_start": HookEventConfig(external=[ExternalHookConfig(command=command)])},
    )

    with pytest.raises(ExternalHookPlaceholderError) as excinfo:
        _hook_entries_for(cfg, "personal", "lh")
    assert command in str(excinfo.value)
    assert field in str(excinfo.value)


def test_deploy_hooks_unknown_placeholder_is_refused_naming_it(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import ExternalHookPlaceholderError, _hook_entries_for

    cfg = _cfg_with_profile(
        tmp_path / "profile",
        hooks={
            "session_start": HookEventConfig(
                external=[ExternalHookConfig(command="notify {nonexistent}")]
            )
        },
    )

    with pytest.raises(ExternalHookPlaceholderError, match="nonexistent") as excinfo:
        _hook_entries_for(cfg, "personal", "lh")
    assert "notify {nonexistent}" in str(excinfo.value)


def test_deploy_hooks_two_profiles_each_get_their_own_config_dir_in_settings(
    tmp_path: Path,
) -> None:
    """End to end through `deploy_hooks`, not only `_hook_entries_for`."""
    lazy_dir = tmp_path / "claude-lazy"
    flex_dir = tmp_path / "claude-flex"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir=str(lazy_dir)),
                "flex": ProfileEntry(config_dir=str(flex_dir)),
            },
        ),
        hooks={
            "session_start": HookEventConfig(
                external=[ExternalHookConfig(command="bash {config_dir}/hooks/herdr.sh")]
            )
        },
    )

    deploy_hooks(cfg)

    lazy_settings = json.dumps(json.loads((lazy_dir / "settings.json").read_text()))
    flex_settings = json.dumps(json.loads((flex_dir / "settings.json").read_text()))
    assert f"bash {lazy_dir}/hooks/herdr.sh" in lazy_settings
    assert f"bash {flex_dir}/hooks/herdr.sh" in flex_settings
    assert str(flex_dir) not in lazy_settings
    assert str(lazy_dir) not in flex_settings


def test_deploy_hooks_does_not_duplicate_a_declared_external_already_installed(
    tmp_path: Path,
) -> None:
    """The third-party installer may have written the same hook itself. Declaring
    it in config must not make it run twice."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    pre = {
        "hooks": {
            "UserPromptSubmit": [
                {"matcher": None, "hooks": [{"type": "command", "command": "/bin/notifier hook"}]}
            ]
        }
    }
    (profile_dir / "settings.json").write_text(json.dumps(pre, indent=2) + "\n")
    cfg = _cfg_with_profile(
        profile_dir,
        hooks={
            "user_prompt_submit": HookEventConfig(
                scripts=[], external=[ExternalHookConfig(command="/bin/notifier hook")]
            )
        },
    )

    deploy_hooks(cfg)

    cc_hooks = json.loads((profile_dir / "settings.json").read_text())["hooks"]
    commands = json.dumps(cc_hooks["UserPromptSubmit"])
    assert commands.count("/bin/notifier hook") == 1


def test_loaded_duplicate_claude_externals_converge_and_omission_preserves_one(
    tmp_path: Path,
) -> None:
    from lazy_harness.core.config import load_config

    profile_dir = tmp_path / "profile"
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '[harness]\nversion = "1"\n'
        '[profiles]\ndefault = "p"\n'
        "[profiles.p]\n"
        f'config_dir = "{profile_dir}"\n'
        "[hooks.session_start]\n"
        "scripts = []\n"
        'external = ["other-tool session", "other-tool session"]\n'
    )

    counts = []
    for _ in range(3):
        deploy_hooks(load_config(config_file))
        groups = json.loads((profile_dir / "settings.json").read_text())["hooks"]["SessionStart"]
        counts.append(len(groups))

    config_file.write_text(
        '[harness]\nversion = "1"\n'
        '[profiles]\ndefault = "p"\n'
        "[profiles.p]\n"
        f'config_dir = "{profile_dir}"\n'
        "[hooks.session_start]\n"
        "scripts = []\n"
    )
    deploy_hooks(load_config(config_file))
    after_omission = json.loads((profile_dir / "settings.json").read_text())["hooks"]

    assert counts == [1, 1, 1]
    assert len(after_omission["SessionStart"]) == 1
    assert after_omission["SessionStart"][0]["hooks"][0]["command"] == "other-tool session"


def test_deploy_hooks_empty_existing_hooks_block(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    (profile_dir / "settings.json").write_text(json.dumps({"hooks": {}}, indent=2) + "\n")
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert "SessionStart" in settings["hooks"]
    assert not (profile_dir / "settings.json.bak").exists()


def test_deploy_hooks_honors_per_event_opt_out(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir, hooks={"pre_compact": HookEventConfig(scripts=[])})

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert "PreCompact" not in settings["hooks"]
    assert "SessionStart" in settings["hooks"]
    assert "Stop" in settings["hooks"]


def test_deploy_hooks_regression_2026_04_17(tmp_path: Path) -> None:
    """Partial user config (only pre_tool_use + post_tool_use declared) must
    not strip the SessionStart / Stop / SessionEnd / PreCompact defaults.
    Captures the real incident from 2026-04-17."""
    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(
        profile_dir,
        hooks={
            "pre_tool_use": HookEventConfig(scripts=["pre-tool-use-security"]),
            "post_tool_use": HookEventConfig(scripts=["post-tool-use-format"]),
        },
    )

    deploy_hooks(cfg)

    cc_hooks = json.loads((profile_dir / "settings.json").read_text())["hooks"]
    assert "SessionStart" in cc_hooks
    assert "Stop" in cc_hooks
    assert "SessionEnd" in cc_hooks
    assert "PreCompact" in cc_hooks
    assert "PostCompact" not in cc_hooks
    # Named by hook, not by the module file inside a deployed path: the command
    # is now `lh hook <name>` and carries no path at all.
    pre_tool_serialized = json.dumps(cc_hooks["PreToolUse"])
    assert "pre-tool-use-security" in pre_tool_serialized
    assert "pre-tool-use-memory-size" not in pre_tool_serialized


def test_a_builtin_hook_deploys_as_a_stable_launcher_invocation() -> None:
    """`f"{sys.executable} {hook.path}"` bakes two machine-specific halves into
    a chezmoi-managed file: the home directory appears in both, and the Python
    minor version appears in the site-packages path. Two machines therefore
    never converge, and every `chezmoi apply` fights the other one.

    `lh hook <name>` carries neither, and resolves through PATH with or without
    a shell — unlike `$HOME/...`, which needs one.
    """
    from lazy_harness.deploy.engine import hook_command
    from lazy_harness.hooks.loader import resolve_hook

    hook = resolve_hook("context-inject", event="session_start")
    assert hook is not None

    command = hook_command(hook, profile="personal")

    assert command == "lh hook context-inject --profile personal"


def test_no_deployed_builtin_command_carries_a_home_or_a_python_version() -> None:
    from lazy_harness.deploy.engine import hook_command
    from lazy_harness.hooks.loader import list_builtin_hooks, resolve_hook

    for name in list_builtin_hooks():
        hook = resolve_hook(name)
        assert hook is not None
        command = hook_command(hook, profile="personal")
        assert "/Users/" not in command and "/home/" not in command, command
        assert "python3." not in command, command
        assert "site-packages" not in command, command


@pytest.mark.parametrize("profile", ["work laptop", "it's-mine", "cost$profile"])
def test_a_profile_needing_quoting_survives_as_one_argument(profile: str) -> None:
    """A profile name is user data, and `core.config` validates nothing about it.

    Interpolated bare, `--profile work laptop` reaches click as two arguments:
    it exits 2 with "Got unexpected extra argument (laptop)", and on PreToolUse
    exit 2 is how Claude Code is told to block the tool call. A usage error in
    a generated command would therefore block the agent's tools.

    The command lands in `settings.json` as a JSON string, so the quoting is
    asserted after a round trip through JSON rather than before it.
    """
    from lazy_harness.deploy.engine import hook_command
    from lazy_harness.hooks.loader import resolve_hook

    hook = resolve_hook("context-inject", event="session_start")
    assert hook is not None

    command = hook_command(hook, profile=profile)

    assert shlex.split(json.loads(json.dumps(command))) == [
        "lh",
        "hook",
        "context-inject",
        "--profile",
        profile,
    ]


def test_a_user_hook_keeps_an_explicit_interpreter_and_path() -> None:
    """There is no stable launcher for a script the framework did not ship, so
    this half is unchanged. It still drifts across machines; the 72 lines the
    change was measured against are all builtins."""
    from pathlib import Path

    from lazy_harness.deploy.engine import hook_command
    from lazy_harness.hooks.loader import HookInfo

    hook = HookInfo(name="mine", path=Path("/home/me/.claude/hooks/mine.py"), is_builtin=False)

    assert hook_command(hook, profile="personal").endswith("/home/me/.claude/hooks/mine.py")


def _hook_entry_count(settings_path: Path) -> int:
    """How many hook entries a deployed settings.json carries, of any origin.

    Deliberately not filtered through `_is_harness_owned`: that predicate is
    what the redeploy test is exercising, and a counter built on it would report
    a stable count while the file doubled in size.
    """
    from lazy_harness.agents.claude_code import _entry_commands

    settings = json.loads(settings_path.read_text())
    return sum(
        1 for entries in settings["hooks"].values() for entry in entries if _entry_commands(entry)
    )


def test_a_generated_builtin_command_is_recognised_as_its_own() -> None:
    """`_is_harness_owned` must recognise what `hook_command` emits.

    The two drifted apart: the classifier matches on a builtins path that the
    generator stopped emitting when it moved to `lh hook <name>`.

    Decision 11 widens the generator to any binary a profile declares, so the
    classifier is checked against both ends of that range rather than only the
    default launcher.
    """
    from lazy_harness.agents.claude_code import _is_harness_owned
    from lazy_harness.deploy.engine import hook_command
    from lazy_harness.hooks.loader import resolve_script_names

    hooks = resolve_script_names(["context-inject"], event="session_start")
    assert hooks, "context-inject should resolve as a builtin"

    default_command = hook_command(hooks[0], profile="personal")
    assert _is_harness_owned(default_command, binaries=DEFAULT_BINARIES), (
        f"the harness does not recognise its own generated command: {default_command!r}"
    )

    beta_command = hook_command(hooks[0], profile="beta", binary="lh-beta")
    assert _is_harness_owned(beta_command, binaries={"lh", "lh-beta"}), (
        f"the harness does not recognise a declared binary's command: {beta_command!r}"
    )


def test_a_legacy_builtin_path_command_is_still_recognised() -> None:
    """Entries written by an older harness carry the interpreter+path form."""
    from lazy_harness.agents.claude_code import _is_harness_owned

    legacy = (
        "/usr/bin/python3 /opt/lib/python3.11/site-packages/"
        "lazy_harness/hooks/builtins/context_inject.py"
    )
    assert _is_harness_owned(legacy, binaries=DEFAULT_BINARIES)


def test_a_foreign_command_is_not_claimed_by_the_harness() -> None:
    """The fix must not over-match: another tool's hook stays foreign."""
    from lazy_harness.agents.claude_code import _is_harness_owned

    assert not _is_harness_owned("/usr/local/bin/my-manual-hook", binaries=DEFAULT_BINARIES)
    assert not _is_harness_owned("npx some-other-tool hook pre-tool-use", binaries=DEFAULT_BINARIES)
    assert not _is_harness_owned("other-tool hook context-inject", binaries=DEFAULT_BINARIES)
    assert not _is_harness_owned("lh status", binaries=DEFAULT_BINARIES)
    assert not _is_harness_owned("echo 'lh hook context-inject'", binaries=DEFAULT_BINARIES)


def test_an_undeclared_binary_is_not_claimed_by_the_harness() -> None:
    """Widening the launcher to a config field must not widen it to any word.

    The owned set is what the artefact records plus the binary being written
    plus the default; a `hook` subcommand alone is not a harness fingerprint, or
    every tool that models hooks the same way would be adopted and then pruned.
    """
    from lazy_harness.agents.claude_code import _is_harness_owned

    binaries = {"lh", "lh-beta"}
    assert _is_harness_owned("lh-beta hook context-inject --profile beta", binaries=binaries)
    assert not _is_harness_owned("lh-other hook context-inject --profile beta", binaries=binaries)
    assert not _is_harness_owned("other-tool hook context-inject --profile beta", binaries=binaries)
    assert not _is_harness_owned(
        "lh-beta hook context-inject --profile beta", binaries=DEFAULT_BINARIES
    )


def test_redeploy_after_a_command_format_change_installs_each_hook_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A redeploy after the generated command format changes must not duplicate.

    This is the round trip that step 1 of the multi-agent design performs: the
    runner gains `--profile <name>`, so every generated command changes shape.
    A classifier that matches on command text cannot recognise the entries the
    previous format wrote, and preserves them as foreign alongside the new ones.
    """
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir, hooks={})
    settings_file = profile_dir / "settings.json"

    # The format that shipped before `--profile`, written by the real generator
    # so the entries are exactly what a deployed profile carries today.
    real_hook_command = engine.hook_command
    monkeypatch.setattr(
        engine,
        "hook_command",
        lambda hook, *, profile, **kwargs: real_hook_command(
            hook, profile=profile, **kwargs
        ).removesuffix(f" --profile {profile}"),
    )
    deploy_hooks(cfg)
    before = _hook_entry_count(settings_file)
    assert before > 0, "the first deploy should install harness hooks"
    assert "--profile" not in settings_file.read_text(), "the first deploy writes the old format"

    monkeypatch.undo()
    capsys.readouterr()

    deploy_hooks(cfg)

    after = _hook_entry_count(settings_file)
    out = capsys.readouterr().out

    assert "preserved" not in out, (
        f"the harness classified its own previous-format entries as foreign:\n{out}"
    )
    assert after == before, (
        f"redeploy after a command format change duplicated hooks: "
        f"{before} hook entries before, {after} after"
    )


def test_deploy_hooks_names_the_binary_each_profile_declares(tmp_path: Path) -> None:
    """Decision 11: the beta unit is a profile, so the binary is resolved inside
    the profile loop. Resolved once above it, every profile would get whichever
    binary was read first — the defect `agent_for_profile` was added to fix."""
    daily_dir = tmp_path / "daily"
    beta_dir = tmp_path / "beta"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(config_dir=str(daily_dir), roots=["~"]),
                "beta": ProfileEntry(
                    config_dir=str(beta_dir), roots=["~"], harness_binary="lh-beta"
                ),
            },
        ),
        hooks={},
    )

    deploy_hooks(cfg)

    daily = (daily_dir / "settings.json").read_text()
    beta = (beta_dir / "settings.json").read_text()

    assert "lh hook context-inject --profile personal" in daily
    assert "lh-beta" not in daily
    assert "lh-beta hook context-inject --profile beta" in beta
    assert '"lh hook' not in beta, "the beta profile must not reach the daily binary"


@pytest.mark.parametrize(
    ("label", "sequence"),
    [
        # The two movements decision 11 exists for. Rolling a beta back is what
        # the design sells as its safety net, and promoting between betas is the
        # only way a beta is ever replaced.
        ("rollback to the default binary", ["", "lh-beta", ""]),
        ("promotion between two betas", ["lh-beta", "lh-gamma"]),
        # The control: a binary that never changes must stay idempotent too, or
        # a fix for the other two could pass by claiming everything in sight.
        ("no change of binary", ["", "", ""]),
    ],
)
def test_a_profile_changing_its_binary_installs_each_hook_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], label: str, sequence: list[str]
) -> None:
    """Ownership must not depend on what the config declares *now*.

    Deriving the allow-list from the live config made the only passing direction
    the one the default binary is permanently in: a profile that stops declaring
    `lh-beta` loses it from the set, and the entries the previous deploy wrote
    are read as another tool's and preserved beside the new ones. Both sequences
    above duplicated every hook — 14 entries became 28 — while the test that
    claimed to cover this only ever walked `"" -> "lh-beta"`.
    """
    profile_dir = tmp_path / "profile"
    settings_file = profile_dir / "settings.json"

    def _cfg(binary: str) -> Config:
        return Config(
            harness=HarnessConfig(version="1"),
            profiles=ProfilesConfig(
                default="beta",
                items={
                    "beta": ProfileEntry(
                        config_dir=str(profile_dir), roots=["~"], harness_binary=binary
                    )
                },
            ),
            hooks={},
        )

    counts: list[int] = []
    for binary in sequence:
        deploy_hooks(_cfg(binary))
        counts.append(_hook_entry_count(settings_file))
        out = capsys.readouterr().out
        assert "preserved" not in out, (
            f"{label}: the harness classified its own entries as foreign "
            f"after deploying {binary or 'the default binary'!r}:\n{out}"
        )

    assert counts[0] > 0, f"{label}: the first deploy should install harness hooks"
    assert len(set(counts)) == 1, (
        f"{label}: redeploying duplicated hooks — entry counts across {sequence} were {counts}"
    )

    # Only the binary from the final deploy may still appear: a surviving
    # command from an earlier one is a duplicate the count alone can miss if
    # a future change ever prunes on a different axis.
    text = settings_file.read_text()
    final = sequence[-1] or "lh"
    for earlier in {b or "lh" for b in sequence} - {final}:
        assert f'"{earlier} hook' not in text, (
            f"{label}: commands for the retired binary {earlier!r} survived"
        )
    assert f"{final} hook context-inject --profile beta" in text


def test_a_deployed_settings_file_declares_the_binary_that_wrote_it(tmp_path: Path) -> None:
    """The generator's half of the ownership contract.

    The classifier reads this back rather than re-deriving the answer from the
    config, which is the only way the two cannot drift apart: a binary the
    harness stopped declaring is still a binary the harness wrote.
    """
    from lazy_harness.core.artifact_version import extract_binary_from_settings

    profile_dir = tmp_path / "profile"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="beta",
            items={
                "beta": ProfileEntry(
                    config_dir=str(profile_dir), roots=["~"], harness_binary="lh-beta"
                )
            },
        ),
        hooks={},
    )

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert extract_binary_from_settings(settings) == "lh-beta"


def test_a_settings_file_written_before_the_stamp_existed_is_still_recognised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The upgrade path: a profile deployed by a version that never wrote the
    stamp, then moved onto a declared binary.

    Its entries say `lh` and the file records nothing, so the only thing that
    can claim them is the default being permanently in the owned set. Without
    it they go foreign on the very first deploy after the upgrade — and the
    first version able to declare a binary is also the first one to stamp it,
    so this is the one window where the file is silent.
    """
    profile_dir = tmp_path / "profile"
    settings_file = profile_dir / "settings.json"

    def _cfg(binary: str) -> Config:
        return Config(
            harness=HarnessConfig(version="1"),
            profiles=ProfilesConfig(
                default="beta",
                items={
                    "beta": ProfileEntry(
                        config_dir=str(profile_dir), roots=["~"], harness_binary=binary
                    )
                },
            ),
            hooks={},
        )

    deploy_hooks(_cfg(""))
    before = _hook_entry_count(settings_file)

    # Strip the stamp the way an older harness left the file: commands written
    # by the default launcher, and nothing recording that it wrote them.
    settings = json.loads(settings_file.read_text())
    del settings["lh_harness_binary"]
    settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    capsys.readouterr()

    deploy_hooks(_cfg("lh-beta"))

    out = capsys.readouterr().out
    assert "preserved" not in out, f"pre-stamp entries were read as foreign:\n{out}"
    assert _hook_entry_count(settings_file) == before
    assert '"lh hook' not in settings_file.read_text()


def test_deploy_hooks_writes_the_writing_version(tmp_path: Path) -> None:
    """Decision 9: the settings.json managed section declares the
    lazy-harness version that wrote it — at the document's top level, not
    inside `hooks` (a `{event: [entry, ...]}` contract the version is not
    an entry of; measurement showed Claude Code tolerates the key in
    either position, so that axis did not decide the placement)."""
    from lazy_harness import __version__
    from lazy_harness.core.artifact_version import extract_from_settings

    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert extract_from_settings(settings) == __version__


def test_deploy_hooks_redeploy_at_same_version_is_byte_identical(tmp_path: Path) -> None:
    """Embedding lh_version must not break idempotence within one version."""
    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)
    first = (profile_dir / "settings.json").read_text()

    deploy_hooks(cfg)
    second = (profile_dir / "settings.json").read_text()

    assert first == second
    assert not (profile_dir / "settings.json.bak").exists()


def test_deploy_hooks_updates_a_stale_lh_version_on_redeploy(tmp_path: Path) -> None:
    """A redeploy overwrites a previously written lh_version, not just hooks."""
    from lazy_harness import __version__
    from lazy_harness.core.artifact_version import extract_from_settings

    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir, hooks={})
    profile_dir.mkdir(parents=True)
    (profile_dir / "settings.json").write_text(
        json.dumps({"lh_version": "0.0.1", "hooks": {}}, indent=2) + "\n"
    )

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert extract_from_settings(settings) == __version__


def test_each_profile_gets_its_own_profile_flag(tmp_path: Path) -> None:
    """Decision 1: the profile is the one fact a running hook needs.

    It names the agent, the config dir, the memory scope and the metrics label,
    so it cannot come from an environment variable or a global config key — two
    profiles on one machine would then resolve to the same answer. It is written
    into each profile's own command, which means the command is generated per
    profile rather than once for all of them.
    """
    from lazy_harness.agents.claude_code import _entry_commands
    from lazy_harness.core.config import Config, HarnessConfig, ProfileEntry, ProfilesConfig

    work = tmp_path / "work"
    play = tmp_path / "play"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="work",
            items={
                "work": ProfileEntry(config_dir=str(work), roots=["~"]),
                "play": ProfileEntry(config_dir=str(play), roots=["~"]),
            },
        ),
        hooks={},
    )

    deploy_hooks(cfg)

    for name, target in (("work", work), ("play", play)):
        commands = [
            cmd
            for entries in json.loads((target / "settings.json").read_text())["hooks"].values()
            for entry in entries
            for cmd in _entry_commands(entry)
            if cmd.startswith("lh hook ")
        ]
        assert commands, f"{name} got no builtin commands"
        for cmd in commands:
            assert cmd.endswith(f" --profile {name}"), cmd


def test_a_deployed_builtin_command_names_its_profile(tmp_path: Path) -> None:
    """The deployed bytes, not the generator in isolation."""
    from lazy_harness.agents.claude_code import _entry_commands

    profile_dir = tmp_path / "profile"

    deploy_hooks(_cfg_with_profile(profile_dir, hooks={}))

    settings = json.loads((profile_dir / "settings.json").read_text())
    commands = [
        cmd
        for entries in settings["hooks"].values()
        for entry in entries
        for cmd in _entry_commands(entry)
        if cmd.startswith("lh hook ")
    ]
    assert commands
    assert all(cmd.endswith(" --profile personal") for cmd in commands), commands
