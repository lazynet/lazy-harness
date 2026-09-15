"""The matcher a builtin is deployed with covers the tools it inspects.

Nothing related the tool names a hook module gates on to the matcher the agent
adapter assigns it from outside, so `pre-tool-use-security` shipped inspecting
four file tools behind a `Bash`-only matcher and its secret-path guard was
never invoked.
"""

from __future__ import annotations

import importlib

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
    generated = ClaudeCodeAdapter()._generate_hook_config({event: [entry]})
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


_MIN_TOOL_GATING_BUILTINS = 7
"""Floor on the size of the watched set, measured on 2026-09-15.

This gate used to pick its subjects by grepping each module for the string
`tool_name`, so migrating a hook to `main(event: HookEvent)` deleted the string
and retired the hook from the gate with nothing red: `pre-tool-use-security` —
the hook the whole suite exists for — was unwatched on `main` @ 75bedaa while
all three tests passed. A subject list that can shrink to nothing while green
is that same defect one level up, so the count is pinned. Retiring a
tool-gating builtin lowers this deliberately; a migration must never.
"""


def _builtins_gating_on_tools() -> list[str]:
    """The builtins that reason about tool calls, per the registry's declaration.

    Keyed on `BuiltinHookSpec.operations`, not on the module's source text.
    `operations` is what a hook *declares* it acts on, independent of how its
    `main()` reads the payload, so migrating a hook cannot narrow this list.
    Dropping the declaration is a visible registry edit, and
    `test_tool_gating_builtins_match_the_modules_declaring_inspected_tools`
    turns it red rather than letting it shrink.
    """
    import lazy_harness.hooks.loader as loader

    return sorted(name for name, spec in loader._BUILTIN_HOOKS.items() if spec.operations)


def _declares_inspected_tools(name: str) -> bool:
    return isinstance(
        getattr(importlib.import_module(_module_of(name)), "INSPECTED_TOOLS", None), frozenset
    )


def _inspected_tools(name: str) -> frozenset[str] | None:
    """`INSPECTED_TOOLS` as the module publishes it, `None` when it does not.

    Never `frozenset()` for a missing constant. An empty set reads as "this
    hook inspects nothing", and every coverage check over it then passes
    vacuously — a deleted declaration would look like a satisfied one.
    """
    if not _declares_inspected_tools(name):
        return None
    return frozenset(importlib.import_module(_module_of(name)).INSPECTED_TOOLS)


def test_the_hook_this_gate_exists_for_is_watched() -> None:
    """Migrating a hook must not retire the gate built after its own incident."""
    assert "pre-tool-use-security" in _builtins_gating_on_tools()


def test_the_watched_set_cannot_silently_shrink() -> None:
    """A gate is only a gate while it still has subjects."""
    watched = _builtins_gating_on_tools()
    assert len(watched) >= _MIN_TOOL_GATING_BUILTINS, (
        f"watched set shrank to {len(watched)} ({watched}); floor is {_MIN_TOOL_GATING_BUILTINS}"
    )


def test_tool_gating_builtins_match_the_modules_declaring_inspected_tools() -> None:
    """Two independent sources, so dropping either fails instead of shrinking.

    The registry says which hooks gate on tools; the modules say which native
    tool names they gate on. Neither can go quiet on its own.
    """
    import lazy_harness.hooks.loader as loader

    declaring = sorted(name for name in loader._BUILTIN_HOOKS if _declares_inspected_tools(name))
    assert declaring == _builtins_gating_on_tools()


def test_every_builtin_gating_on_tools_declares_what_it_inspects() -> None:
    """A matcher can only be checked against a set the module publishes."""
    missing = [name for name in _builtins_gating_on_tools() if _inspected_tools(name) is None]
    assert missing == [], f"no INSPECTED_TOOLS declared by: {missing}"


def test_deployed_matcher_covers_every_tool_each_builtin_inspects() -> None:
    """The gate the `pre-tool-use-security` matcher bug slipped through."""
    gaps: dict[str, list[str]] = {}
    for name in _builtins_gating_on_tools():
        inspected = _inspected_tools(name)
        if inspected is None:
            gaps[name] = ["<no INSPECTED_TOOLS to check the matcher against>"]
            continue
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
