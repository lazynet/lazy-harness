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


def test_migrated_agrees_with_the_signature_in_both_directions() -> None:
    """Flipping `migrated` and changing the signature are one change, both ways.

    `True` on a module whose `main()` still takes no arguments hands it an
    event object; `False` on one that takes an event calls it with nothing. The
    field is what both entry points route on, so either mismatch is a hook that
    raises on its first real invocation and nowhere earlier.

    Read off every registered module rather than checked against a literal
    list. A list has to be appended to by each of step 5's fifteen migrations —
    fifteen edits to one line, in fifteen branches — and it only ever restates
    what `inspect.signature` can be asked directly.
    """
    for name, spec in _BUILTIN_HOOKS.items():
        module = importlib.import_module(spec.module)
        takes_event = list(inspect.signature(module.main).parameters) == ["event"]
        assert spec.migrated == takes_event, (
            f"{name}: migrated={spec.migrated} but main() "
            f"{'takes' if takes_event else 'does not take'} an event"
        )
        if not spec.migrated:
            continue
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


def test_no_unmigrated_builtin_declares_a_signal() -> None:
    """`signals` is the one spec field that is live before the migration.

    `event`, `operations` and `blocking` are inert while `migrated` is False:
    `runner.run_hook` is the only reader of the first and third and both entry
    points reach it only for a migrated spec (`engine.py:59`,
    `cli/hooks_cmd.py:96`), and `operations` has no reader in `src/` at all.
    So step 5 can declare those early, in one reviewable diff.

    `signals` cannot travel with them, and not because migration changes what
    it does -- measured, it changes nothing. `signal_gaps.gaps_for_profile`
    reads it through `loader.builtin_signals` without consulting `migrated`,
    and `deploy.engine` leaves a hook with an undeliverable signal out of the
    generated settings. Against a profile whose agent supplies no
    `TranscriptReader` -- `codex.py` ships none today, so it delivers the empty
    set -- `session-export` declaring `MESSAGES` produces the same omission at
    `migrated=False` and at `migrated=True`.

    That symmetry is the reason for the gate rather than an argument against
    it. The other three fields are inert, so declaring them early costs
    nothing if a row is wrong. `signals` is live in both states, so a wrong row
    silently undeploys a working hook the moment any profile runs a reader-less
    agent -- and a bulk commit declaring fourteen of them carries evidence for
    none. Hence: a builtin's `signals` lands in the commit that migrates it,
    beside the golden and the isolation assertion that show what that hook
    actually reads.
    """
    early = sorted(
        name for name, spec in _BUILTIN_HOOKS.items() if spec.signals and not spec.migrated
    )
    assert early == [], (
        f"signals declared before migration, undeployable on a reader-less agent: {early}"
    )


def test_a_declared_event_is_one_the_agent_delivers() -> None:
    """A canonical name no adapter knows would fail only at hook time."""
    supported = set(ClaudeCodeAdapter().hook_events())
    for name, spec in _BUILTIN_HOOKS.items():
        if spec.event is not None:
            assert spec.event in supported, f"{name}: {spec.event}"
