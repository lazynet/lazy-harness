"""The matcher a builtin is deployed with covers the tools it inspects.

Nothing related the tool names a hook module gates on to the matcher the agent
adapter assigns it from outside, so `pre-tool-use-security` shipped inspecting
four file tools behind a `Bash`-only matcher and its secret-path guard was
never invoked.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from lazy_harness.agents.base import HookEntry
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.hooks.loader import resolve_hook

_CC_TOOL_EVENTS = {"pre_tool_use": "PreToolUse", "post_tool_use": "PostToolUse"}


def _deployed_matcher(name: str, event: str) -> str:
    """The matcher `lh deploy` would write to settings.json for this hook."""
    hook = resolve_hook(name, event=event)
    assert hook is not None, f"unresolvable builtin: {name}"
    entry: str | HookEntry = (
        HookEntry(command="cmd", matcher=hook.matcher) if hook.matcher is not None else "cmd"
    )
    generated = ClaudeCodeAdapter().generate_hook_config({event: [entry]})
    return generated[_CC_TOOL_EVENTS[event]][0]["matcher"]


def _covers(matcher: str, tool: str) -> bool:
    return matcher in ("", "*") or tool in matcher.split("|")


def test_security_hook_is_deployed_for_every_tool_it_inspects() -> None:
    """The tool names are spelled out: they are the contract with the agent."""
    matcher = _deployed_matcher("pre-tool-use-security", "pre_tool_use")
    uncovered = sorted(
        tool
        for tool in ("Bash", "Read", "Edit", "Write", "NotebookEdit")
        if not _covers(matcher, tool)
    )
    assert uncovered == [], f"matcher {matcher!r} never reaches {uncovered}"


def _tool_event_for(name: str) -> str | None:
    """The event a builtin is registered under, when the registry fixes one."""
    from lazy_harness.plugins.builtins import builtin_registry

    for cap in builtin_registry().capabilities(kind="hook"):
        if cap.name == name:
            event = cap.config_path.split(".")[1]
            return event if event in _CC_TOOL_EVENTS else None
    return None


def _builtins_gating_on_tool_name() -> list[str]:
    import lazy_harness.hooks.loader as loader

    names = []
    for name, spec in loader._BUILTIN_HOOKS.items():
        module = importlib.import_module(spec.module)
        source = Path(str(module.__file__)).read_text()
        if "tool_name" in source:
            names.append(name)
    return names


def test_every_builtin_gating_on_tool_name_declares_what_it_inspects() -> None:
    """A matcher can only be checked against a set the module publishes."""
    missing = [
        name
        for name in _builtins_gating_on_tool_name()
        if not isinstance(
            getattr(importlib.import_module(_module_of(name)), "INSPECTED_TOOLS", None),
            frozenset,
        )
    ]
    assert missing == [], f"no INSPECTED_TOOLS declared by: {missing}"


def test_deployed_matcher_covers_every_tool_each_builtin_inspects() -> None:
    """The gate the `pre-tool-use-security` matcher bug slipped through."""
    gaps: dict[str, list[str]] = {}
    for name in _builtins_gating_on_tool_name():
        module = importlib.import_module(_module_of(name))
        inspected = getattr(module, "INSPECTED_TOOLS", frozenset())
        fixed = _tool_event_for(name)
        events = [fixed] if fixed else list(_CC_TOOL_EVENTS)
        for event in events:
            matcher = _deployed_matcher(name, str(event))
            uncovered = sorted(t for t in inspected if not _covers(matcher, t))
            if uncovered:
                gaps[f"{name}@{event}"] = uncovered
    assert gaps == {}, f"matchers that never reach the inspected tools: {gaps}"


def _module_of(name: str) -> str:
    import lazy_harness.hooks.loader as loader

    return loader._BUILTIN_HOOKS[name].module
