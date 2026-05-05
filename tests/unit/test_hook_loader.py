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
