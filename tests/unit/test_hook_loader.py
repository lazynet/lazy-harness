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
    assert (
        _BUILTIN_HOOKS["pre-tool-use-security"]
        == "lazy_harness.hooks.builtins.pre_tool_use_security"
    )


def test_pre_tool_use_security_resolves_to_concrete_file() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    info = resolve_hook("pre-tool-use-security")
    assert info is not None
    assert info.is_builtin is True
    assert info.path.name == "pre_tool_use_security.py"
    assert info.path.is_file()
