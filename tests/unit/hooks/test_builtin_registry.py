"""The builtin registry mirrors the builtins directory, entry for entry.

`BuiltinHookSpec.migrated` decides which execution path a builtin takes, so a
module the registry does not carry is a hook with no declared path rather than
a hook with a safe default: neither entry point would ever reach it. The list
is static and the directory is not, so completeness is asserted against the
glob rather than maintained by hand.
"""

from __future__ import annotations

import importlib
import inspect
import typing
from pathlib import Path

from lazy_harness.agents.base import HookDecision, HookEvent
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.hooks.loader import _BUILTIN_HOOKS

_BUILTINS_DIR = Path(__file__).resolve().parents[3] / "src" / "lazy_harness" / "hooks" / "builtins"

#: Not hooks: the package marker and the helpers every hook imports.
_NOT_HOOKS = {"__init__", "_shared"}


def _modules_on_disk() -> set[str]:
    return {p.stem for p in _BUILTINS_DIR.glob("*.py") if p.stem not in _NOT_HOOKS}


def _modules_in_registry() -> set[str]:
    return {spec.module.rsplit(".", 1)[-1] for spec in _BUILTIN_HOOKS.values()}


def test_every_builtin_module_on_disk_is_registered() -> None:
    unregistered = sorted(_modules_on_disk() - _modules_in_registry())
    assert unregistered == [], f"builtins with no registry entry: {unregistered}"


def test_no_registry_entry_names_a_module_that_is_not_there() -> None:
    dangling = sorted(_modules_in_registry() - _modules_on_disk())
    assert dangling == [], f"registry entries with no module: {dangling}"


def test_each_registered_name_maps_to_a_module_of_its_own() -> None:
    """One name, one module: a shared module would give two hooks one marker."""
    assert len(_modules_in_registry()) == len(_BUILTIN_HOOKS)


#: Step 2 of `specs/designs/2026-09-13-multi-agent-harness-design.md` migrates
#: exactly these, chosen because between them they cover all three ways a hook
#: answers: deny via stderr and exit 2, block via stdout, and context with no
#: verdict at all. Step 5 migrates the remaining fifteen.
_MIGRATED_IN_STEP_2 = ["context-inject", "pre-tool-use-security", "stop-verify-guard"]


def test_exactly_the_step_two_builtins_are_migrated() -> None:
    """Flipping `migrated` and changing the signature are one change, both ways.

    `True` on a module whose `main()` still takes no arguments hands it an
    event object; `False` on one that takes an event calls it with nothing. The
    field is what both entry points route on, so either mismatch is a hook that
    raises on its first real invocation and nowhere earlier.
    """
    migrated = sorted(name for name, spec in _BUILTIN_HOOKS.items() if spec.migrated)
    assert migrated == _MIGRATED_IN_STEP_2


def test_every_migrated_builtin_takes_an_event_and_returns_a_decision() -> None:
    """The signature itself, read off the module the registry names."""
    for name in _MIGRATED_IN_STEP_2:
        module = importlib.import_module(_BUILTIN_HOOKS[name].module)
        signature = inspect.signature(module.main)
        assert list(signature.parameters) == ["event"], name
        hints = typing.get_type_hints(module.main)
        assert hints["event"] is HookEvent, name
        assert hints["return"] is HookDecision, name


def test_every_migrated_builtin_declares_the_event_it_is_wired_to() -> None:
    """The runner's fallback when a payload does not name one — see `loader`.

    `lh hook <name>` has no event flag, so a migrated hook with no declared
    event cannot be parsed or serialised at all on that path.
    """
    undeclared = sorted(
        name for name, spec in _BUILTIN_HOOKS.items() if spec.migrated and not spec.event
    )
    assert undeclared == []


def test_a_declared_event_is_one_the_agent_delivers() -> None:
    """A canonical name no adapter knows would fail only at hook time."""
    supported = set(ClaudeCodeAdapter().hook_events())
    for name, spec in _BUILTIN_HOOKS.items():
        if spec.event is not None:
            assert spec.event in supported, f"{name}: {spec.event}"
