"""Tests for the deploy.defaults module — default hook set + merge logic."""

from __future__ import annotations

from lazy_harness.core.config import HookEventConfig
from lazy_harness.deploy.defaults import DEFAULT_HOOKS, merge_with_defaults
from lazy_harness.hooks.loader import list_builtin_hooks


def test_default_hooks_only_references_registered_builtins() -> None:
    builtins = set(list_builtin_hooks())
    for event, scripts in DEFAULT_HOOKS.items():
        for script in scripts:
            assert script in builtins, (
                f"DEFAULT_HOOKS[{event!r}] references {script!r}, "
                "which is not in lazy_harness.hooks.loader._BUILTIN_HOOKS"
            )


def test_merge_empty_user_returns_defaults_verbatim() -> None:
    result = merge_with_defaults({})

    assert result == {k: list(v) for k, v in DEFAULT_HOOKS.items()}
    result["session_start"].append("mutated")
    assert "mutated" not in DEFAULT_HOOKS["session_start"]


def test_merge_user_overrides_one_event() -> None:
    user = {"session_stop": HookEventConfig(scripts=["my-hook"])}

    result = merge_with_defaults(user)

    assert result["session_stop"] == ["my-hook"]
    assert result["session_start"] == ["context-inject"]
    assert result["pre_tool_use"] == ["pre-tool-use-security", "pre-tool-use-memory-size"]


def test_merge_user_empty_list_is_explicit_opt_out() -> None:
    user = {"session_stop": HookEventConfig(scripts=[])}

    result = merge_with_defaults(user)

    assert result["session_stop"] == []
    assert result["session_start"] == ["context-inject"]


def test_merge_preserves_user_custom_event() -> None:
    user = {"notification": HookEventConfig(scripts=["my-notify"])}

    result = merge_with_defaults(user)

    assert result["notification"] == ["my-notify"]
    assert result["session_start"] == ["context-inject"]
