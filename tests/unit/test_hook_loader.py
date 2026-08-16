"""Tests for hook discovery and loading."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import Config, HarnessConfig, HookEventConfig


def test_resolve_builtin_hook() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    result = resolve_hook("context-inject")
    assert result is not None
    assert result.name == "context-inject"
    assert result.is_builtin is True


def test_resolve_user_hook(tmp_path: Path) -> None:
    from lazy_harness.hooks.loader import resolve_hook

    user_hooks_dir = tmp_path / "hooks"
    user_hooks_dir.mkdir()
    script = user_hooks_dir / "my-hook.py"
    script.write_text("#!/usr/bin/env python3\nprint('hello')\n")
    script.chmod(0o755)

    result = resolve_hook("my-hook", user_hooks_dir=user_hooks_dir)
    assert result is not None
    assert result.name == "my-hook"
    assert result.is_builtin is False


def test_resolve_unknown_hook() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    result = resolve_hook("nonexistent-hook")
    assert result is None


def test_resolve_hooks_for_event() -> None:
    from lazy_harness.hooks.loader import resolve_hooks_for_event

    cfg = Config(
        harness=HarnessConfig(version="1"),
        hooks={"session_start": HookEventConfig(scripts=["context-inject"])},
    )
    hooks = resolve_hooks_for_event(cfg, "session_start")
    assert len(hooks) == 1
    assert hooks[0].name == "context-inject"


def test_resolve_hooks_for_unconfigured_event() -> None:
    from lazy_harness.hooks.loader import resolve_hooks_for_event

    cfg = Config(harness=HarnessConfig(version="1"))
    hooks = resolve_hooks_for_event(cfg, "session_start")
    assert hooks == []


def test_list_builtin_hooks() -> None:
    from lazy_harness.hooks.loader import list_builtin_hooks

    builtins = list_builtin_hooks()
    assert "context-inject" in builtins
    assert "pre-compact" in builtins
    assert "session-end" in builtins


def test_resolve_session_end_builtin_hook() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    result = resolve_hook("session-end")
    assert result is not None
    assert result.name == "session-end"
    assert result.is_builtin is True


def test_pre_tool_use_security_is_registered_as_builtin() -> None:
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS

    assert "pre-tool-use-security" in _BUILTIN_HOOKS
    spec = _BUILTIN_HOOKS["pre-tool-use-security"]
    assert spec.module == "lazy_harness.hooks.builtins.pre_tool_use_security"


def test_pre_tool_use_security_resolves_to_concrete_file() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    info = resolve_hook("pre-tool-use-security")
    assert info is not None
    assert info.is_builtin is True
    assert info.path.name == "pre_tool_use_security.py"
    assert info.path.is_file()


def test_post_tool_use_format_is_registered_as_builtin() -> None:
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS

    assert "post-tool-use-format" in _BUILTIN_HOOKS
    spec = _BUILTIN_HOOKS["post-tool-use-format"]
    assert spec.module == "lazy_harness.hooks.builtins.post_tool_use_format"


def test_post_tool_use_format_resolves_to_concrete_file() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    info = resolve_hook("post-tool-use-format")
    assert info is not None
    assert info.is_builtin is True
    assert info.path.name == "post_tool_use_format.py"
    assert info.path.is_file()


def test_post_tool_use_sync_claude_is_registered_as_builtin() -> None:
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS

    assert "post-tool-use-sync-claude" in _BUILTIN_HOOKS
    spec = _BUILTIN_HOOKS["post-tool-use-sync-claude"]
    assert spec.module == "lazy_harness.hooks.builtins.post_tool_use_sync_claude"


def test_post_tool_use_sync_claude_resolves_to_concrete_file() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    info = resolve_hook("post-tool-use-sync-claude")
    assert info is not None
    assert info.is_builtin is True
    assert info.path.name == "post_tool_use_sync_claude.py"
    assert info.path.is_file()


def test_post_compact_is_registered_as_builtin() -> None:
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS

    assert "post-compact" in _BUILTIN_HOOKS
    spec = _BUILTIN_HOOKS["post-compact"]
    assert spec.module == "lazy_harness.hooks.builtins.post_compact"


def test_builtin_hook_spec_carries_optional_matcher() -> None:
    from lazy_harness.hooks.loader import BuiltinHookSpec

    spec = BuiltinHookSpec(module="x.y", matcher="Edit|Write")
    assert spec.module == "x.y"
    assert spec.matcher == "Edit|Write"

    spec_no_matcher = BuiltinHookSpec(module="x.y")
    assert spec_no_matcher.matcher is None


def test_resolve_hook_carries_matcher_when_spec_has_one(monkeypatch) -> None:
    from lazy_harness.hooks import loader
    from lazy_harness.hooks.loader import BuiltinHookSpec, resolve_hook

    monkeypatch.setitem(
        loader._BUILTIN_HOOKS,
        "test-hook-with-matcher",
        BuiltinHookSpec(
            module="lazy_harness.hooks.builtins.pre_tool_use_security",
            matcher="Edit|Write",
        ),
    )
    info = resolve_hook("test-hook-with-matcher")
    assert info is not None
    assert info.matcher == "Edit|Write"


def test_resolve_hook_matcher_defaults_to_none_when_spec_has_no_matcher() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    info = resolve_hook("pre-tool-use-security")
    assert info is not None
    assert info.matcher is None


def test_pre_tool_use_memory_size_is_registered_with_edit_write_matcher() -> None:
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS, resolve_hook

    assert "pre-tool-use-memory-size" in _BUILTIN_HOOKS
    spec = _BUILTIN_HOOKS["pre-tool-use-memory-size"]
    assert spec.module == "lazy_harness.hooks.builtins.pre_tool_use_memory_size"
    assert spec.matcher == "Edit|Write"

    info = resolve_hook("pre-tool-use-memory-size")
    assert info is not None
    assert info.matcher == "Edit|Write"
    assert info.path.name == "pre_tool_use_memory_size.py"
    assert info.path.is_file()


def test_post_compact_resolves_to_concrete_file() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    info = resolve_hook("post-compact")
    assert info is not None
    assert info.is_builtin is True
    assert info.path.name == "post_compact.py"
    assert info.path.is_file()


def test_resolve_script_names_returns_hookinfo_list() -> None:
    from lazy_harness.hooks.loader import resolve_script_names

    result = resolve_script_names(["context-inject"])

    assert len(result) == 1
    assert result[0].name == "context-inject"
    assert result[0].is_builtin is True


def test_resolve_script_names_skips_unresolvable() -> None:
    from lazy_harness.hooks.loader import resolve_script_names

    result = resolve_script_names(["context-inject", "no-such-hook-xyz"])

    assert [h.name for h in result] == ["context-inject"]


def test_pre_tool_use_read_size_is_registered_with_read_matcher() -> None:
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS, resolve_hook

    assert "pre-tool-use-read-size" in _BUILTIN_HOOKS
    spec = _BUILTIN_HOOKS["pre-tool-use-read-size"]
    assert spec.module == "lazy_harness.hooks.builtins.pre_tool_use_read_size"
    assert spec.matcher == "Read"

    info = resolve_hook("pre-tool-use-read-size")
    assert info is not None
    assert info.matcher == "Read"
    assert info.path.name == "pre_tool_use_read_size.py"
    assert info.path.is_file()


def test_ansible_lint_hook_is_registered_with_edit_write_matcher() -> None:
    from lazy_harness.hooks.loader import list_builtin_hooks, resolve_hook

    assert "post-tool-use-ansible-lint" in list_builtin_hooks()
    info = resolve_hook("post-tool-use-ansible-lint")
    assert info is not None
    assert info.is_builtin is True
    assert info.matcher == "Edit|Write"


def test_herdr_context_gauge_hook_is_registered_without_a_matcher() -> None:
    """Stop carries no tool matcher — an inherited Edit|Write default would
    silence the gauge on every turn that ended without a file edit."""
    from lazy_harness.hooks.loader import list_builtin_hooks, resolve_hook

    assert "herdr-context-gauge" in list_builtin_hooks()
    info = resolve_hook("herdr-context-gauge")
    assert info is not None
    assert info.is_builtin is True
    assert info.matcher is None
    assert info.path.name == "herdr_context_gauge.py"
    assert info.path.is_file()


def test_resolve_hook_picks_the_matcher_for_the_requested_event(monkeypatch) -> None:
    """A hook wired to several events needs a matcher per event: `*` is right
    for PostToolUse and meaningless on Stop."""
    from lazy_harness.hooks import loader
    from lazy_harness.hooks.loader import BuiltinHookSpec, resolve_hook

    monkeypatch.setitem(
        loader._BUILTIN_HOOKS,
        "test-hook-per-event",
        BuiltinHookSpec(
            module="lazy_harness.hooks.builtins.pre_tool_use_security",
            matcher={"post_tool_use": "*"},
        ),
    )

    info = resolve_hook("test-hook-per-event", event="post_tool_use")
    assert info is not None
    assert info.matcher == "*"


def test_resolve_hook_falls_back_to_no_matcher_for_unlisted_events(monkeypatch) -> None:
    """An event the mapping does not name takes the event's own default."""
    from lazy_harness.hooks import loader
    from lazy_harness.hooks.loader import BuiltinHookSpec, resolve_hook

    monkeypatch.setitem(
        loader._BUILTIN_HOOKS,
        "test-hook-per-event",
        BuiltinHookSpec(
            module="lazy_harness.hooks.builtins.pre_tool_use_security",
            matcher={"post_tool_use": "*"},
        ),
    )

    info = resolve_hook("test-hook-per-event", event="session_stop")
    assert info is not None
    assert info.matcher is None


def test_a_plain_string_matcher_still_applies_to_every_event() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    info = resolve_hook("pre-tool-use-memory-size", event="pre_tool_use")
    assert info is not None
    assert info.matcher == "Edit|Write"


def test_herdr_context_gauge_matches_every_tool_on_post_tool_use() -> None:
    """The tools that grow a context window are Read, Bash, Grep and Task — the
    `Edit|Write` default for PostToolUse would sample almost none of them."""
    from lazy_harness.hooks.loader import resolve_hook

    info = resolve_hook("herdr-context-gauge", event="post_tool_use")
    assert info is not None
    assert info.matcher == "*"


def test_herdr_context_gauge_carries_no_matcher_on_lifecycle_events() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    for event in ("session_stop", "session_start", "session_end"):
        info = resolve_hook("herdr-context-gauge", event=event)
        assert info is not None
        assert info.matcher is None, event


def test_generated_settings_carry_the_per_event_matcher_end_to_end() -> None:
    """Resolution and generation are separate steps; a matcher that survives one
    and not the other still ships a broken settings.json."""
    from lazy_harness.agents.base import HookEntry
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.hooks.loader import resolve_script_names

    entries: dict[str, list[str | HookEntry]] = {}
    for event in ("session_stop", "post_tool_use"):
        resolved = []
        for hook in resolve_script_names(["herdr-context-gauge"], event=event):
            command = f"python {hook.path}"
            resolved.append(
                HookEntry(command=command, matcher=hook.matcher)
                if hook.matcher is not None
                else command
            )
        entries[event] = resolved

    generated = ClaudeCodeAdapter().generate_hook_config(entries)

    assert generated["PostToolUse"][0]["matcher"] == "*"
    assert generated["Stop"][0]["matcher"] == ""


def test_generated_settings_never_carry_a_null_matcher() -> None:
    """A null matcher makes Claude Code reject the whole settings file, taking
    every other hook down with it."""
    from lazy_harness.agents.base import HookEntry
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.hooks.loader import list_builtin_hooks, resolve_script_names

    entries: dict[str, list[str | HookEntry]] = {}
    for event in ("session_start", "session_stop", "session_end", "post_tool_use"):
        resolved = []
        for hook in resolve_script_names(list_builtin_hooks(), event=event):
            command = f"python {hook.path}"
            resolved.append(
                HookEntry(command=command, matcher=hook.matcher)
                if hook.matcher is not None
                else command
            )
        entries[event] = resolved

    generated = ClaudeCodeAdapter().generate_hook_config(entries)

    for cc_event, groups in generated.items():
        for group in groups:
            assert isinstance(group["matcher"], str), f"{cc_event} carries a non-string matcher"


def test_user_prompt_goal_is_registered_as_builtin() -> None:
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS

    assert "user-prompt-goal" in _BUILTIN_HOOKS
    spec = _BUILTIN_HOOKS["user-prompt-goal"]
    assert spec.module == "lazy_harness.hooks.builtins.user_prompt_goal"


def test_user_prompt_goal_resolves_to_concrete_file() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    info = resolve_hook("user-prompt-goal")
    assert info is not None
    assert info.is_builtin is True
    assert info.path.name == "user_prompt_goal.py"
    assert info.path.is_file()
