"""Tests for deploy_hooks — engine-level integration with merge_with_defaults."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.core.config import (
    Config,
    ExternalHookConfig,
    HarnessConfig,
    HookEventConfig,
    ProfileEntry,
    ProfilesConfig,
)
from lazy_harness.deploy.engine import deploy_hooks


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

    command = hook_command(hook)

    assert command == "lh hook context-inject"


def test_no_deployed_builtin_command_carries_a_home_or_a_python_version() -> None:
    from lazy_harness.deploy.engine import hook_command
    from lazy_harness.hooks.loader import list_builtin_hooks, resolve_hook

    for name in list_builtin_hooks():
        hook = resolve_hook(name)
        assert hook is not None
        command = hook_command(hook)
        assert "/Users/" not in command and "/home/" not in command, command
        assert "python3." not in command, command
        assert "site-packages" not in command, command


def test_a_user_hook_keeps_an_explicit_interpreter_and_path() -> None:
    """There is no stable launcher for a script the framework did not ship, so
    this half is unchanged. It still drifts across machines; the 72 lines the
    change was measured against are all builtins."""
    from pathlib import Path

    from lazy_harness.deploy.engine import hook_command
    from lazy_harness.hooks.loader import HookInfo

    hook = HookInfo(name="mine", path=Path("/home/me/.claude/hooks/mine.py"), is_builtin=False)

    assert hook_command(hook).endswith("/home/me/.claude/hooks/mine.py")
