"""`BuiltinHookSpec.signals` answers per placement, not per spec.

One spec is installed once per event it is wired to, and `herdr-context-gauge`
is the hook whose placements disagree about what they read: three of its four
open the transcript for token usage, and the `SessionEnd` one deliberately does
not (`herdr_context_gauge.py:175` short-circuits before `_tokens_of`). A single
flat declaration has no right answer there. `TOKEN_USAGE` makes `deploy` omit
the retract as well as the publishes, leaving a dead session's gauge on the pane
forever; declaring nothing leaves three placements installing on an agent that
can never feed them, green because they cannot fail.

The field therefore widens the way `matcher` already did, for this same hook and
this same reason — `loader.py:22-26` says a mapping "lets one hook carry
different matchers per event, which a hook wired to both tool and lifecycle
events needs: `*` is correct for PostToolUse and meaningless on Stop". The
signal sets are the second fact about this hook that varies by placement, so
they take the shape the first one already has.

Widening a type is a gate in this repository's `CLAUDE.md`:

    One answer lives in one importable place; every path naming it is derived
    from it or audited against it. [...] Widening a type audits every path
    naming that type *or its config*, not just the `Protocol` methods.

`test_the_registry_is_the_only_module_that_reads_the_signals_field` below is
that audit, executable rather than recorded in a design document — and the flat
path is covered first and separately, because sixteen of the eighteen registered
specs still use it and task 11 is about to write a seventeenth.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lazy_harness.agents.base import Signal
from lazy_harness.hooks.loader import _BUILTIN_HOOKS, BuiltinHookSpec, builtin_signals

# --- the flat path, which is what almost every spec uses --------------------- #


def test_a_flat_frozenset_answers_for_every_event() -> None:
    """The overwhelmingly common declaration, unchanged by the widening.

    A flat set describes a hook whose reads do not vary by placement, so the
    event is not consulted at all — including when there is no event to consult.
    """
    spec = BuiltinHookSpec(module="x", signals=frozenset({Signal.GOAL_STATUS}))

    assert spec.signals_for("session_stop") == frozenset({Signal.GOAL_STATUS})
    assert spec.signals_for("post_tool_use") == frozenset({Signal.GOAL_STATUS})
    assert spec.signals_for(None) == frozenset({Signal.GOAL_STATUS})


def test_the_default_is_an_empty_flat_set() -> None:
    assert BuiltinHookSpec(module="x").signals_for("session_stop") == frozenset()


def test_every_registered_spec_answers_a_flat_call_with_a_frozenset() -> None:
    """No caller may receive a `Mapping` where it expected a set.

    `signal_gaps.py` subtracts the answer from the reader's vocabulary
    (`missing = builtin_signals(...) - delivered`). A `Mapping` reaching that
    line raises `TypeError` inside a deploy, so the accessor must never hand one
    back regardless of how the spec spelled its declaration.
    """
    for name in _BUILTIN_HOOKS:
        assert isinstance(builtin_signals(name), frozenset), name


def test_the_registry_still_holds_flat_declarations() -> None:
    """Guards the claim the widening rests on: this is not a migration of all specs.

    If a later change quietly converted every spec to a mapping, the flat branch
    above would still pass while covering nothing that ships.
    """
    flat = [
        name
        for name, spec in _BUILTIN_HOOKS.items()
        if not isinstance(spec.signals, dict) and not isinstance(spec.signals, type(None))
    ]

    assert len(flat) >= 16, f"expected the flat form to remain the norm, got {len(flat)}"


# --- the mapping path -------------------------------------------------------- #


def _per_placement() -> BuiltinHookSpec:
    """The shape `herdr-context-gauge` declares: three placements read, one does not."""
    return BuiltinHookSpec(
        module="x",
        signals={
            "post_tool_use": frozenset({Signal.TOKEN_USAGE}),
            "session_stop": frozenset({Signal.TOKEN_USAGE}),
            "session_start": frozenset({Signal.TOKEN_USAGE}),
        },
    )


def test_a_mapping_answers_the_placement_it_names() -> None:
    spec = _per_placement()

    assert spec.signals_for("post_tool_use") == frozenset({Signal.TOKEN_USAGE})
    assert spec.signals_for("session_stop") == frozenset({Signal.TOKEN_USAGE})
    assert spec.signals_for("session_start") == frozenset({Signal.TOKEN_USAGE})


def test_a_placement_the_mapping_omits_declares_nothing() -> None:
    """The assertion the whole decision rests on.

    `session_end` is absent from the mapping, so it needs nothing and deploy
    must not omit it. Were this to return the union of the declared sets — the
    obvious wrong implementation, and the one that reads as "the hook needs
    token usage" — the retract would be omitted on exactly the agents where a
    stale gauge can never be cleared by anything else.
    """
    assert _per_placement().signals_for("session_end") == frozenset()


def test_a_mapping_with_no_event_at_all_declares_nothing() -> None:
    """There is no placement to answer for, and a union would be a guess.

    `matcher_for` resolves the same way (`loader.py:88-91`): a mapping with no
    event returns `None` rather than picking one of its entries.
    """
    assert _per_placement().signals_for(None) == frozenset()


def test_builtin_signals_passes_the_event_through_to_the_spec() -> None:
    """The accessor, not the field, is what callers reach — through the event."""
    assert builtin_signals("herdr-context-gauge", event="session_stop") == frozenset(
        {Signal.TOKEN_USAGE}
    )
    assert builtin_signals("herdr-context-gauge", event="session_end") == frozenset()


def test_builtin_signals_still_takes_one_argument() -> None:
    """Callers that have no event keep working, and get the conservative answer.

    `lh doctor`'s feature rows and any future caller outside the per-event loop
    ask "what does this hook need" with nothing to key on. Returning the empty
    set rather than raising keeps that question answerable.
    """
    assert builtin_signals("herdr-context-gauge") == frozenset()
    assert builtin_signals("stop-verify-guard") == frozenset({Signal.GOAL_STATUS})


# --- the blast-radius audit, executable -------------------------------------- #

_SRC = Path(__file__).resolve().parents[3] / "src" / "lazy_harness"


def _modules_naming_the_field() -> set[str]:
    """Every shipped module with a `.signals` attribute access on a spec.

    Parsed rather than grepped so that `reader.signals()` — the supply side on
    `TranscriptReader`, a different question with the same spelling — does not
    count. A call is excluded; a plain attribute read is not.
    """
    found: set[str] = set()
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = {
            node.func
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "signals" and node not in calls:
                found.add(str(path.relative_to(_SRC)))
    return found


def test_the_registry_is_the_only_module_that_reads_the_signals_field() -> None:
    """The audit `CLAUDE.md` demands of a widened type, as a test rather than a table.

    Any other module reading `spec.signals` directly would be reading a value
    whose type now depends on the spec, and would answer a per-event question
    with a whole-spec answer. `loader.py` owns the field; everyone else goes
    through `signals_for` or `builtin_signals`.
    """
    assert _modules_naming_the_field() == {"hooks/loader.py"}


def test_the_only_caller_of_builtin_signals_supplies_an_event() -> None:
    """`signal_gaps.py:74` is the one production reader, and it is already per-event.

    This is why the widening is cheap and why it must not be undone: the deploy
    filter keys its omissions by `(event, hook)` (`deploy/engine.py:263`) and
    `_report_omitted` looks them up the same way. The pipeline was per-placement
    before this change; only the declaration was not.
    """
    source = (_SRC / "hooks" / "signal_gaps.py").read_text(encoding="utf-8")

    assert "builtin_signals(name, event=event)" in source


# --- the end-to-end consequence ---------------------------------------------- #


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("post_tool_use", frozenset({Signal.TOKEN_USAGE})),
        ("session_stop", frozenset({Signal.TOKEN_USAGE})),
        ("session_start", frozenset({Signal.TOKEN_USAGE})),
        ("session_end", frozenset()),
    ],
)
def test_the_gauge_declares_token_usage_everywhere_but_the_retract(
    event: str, expected: frozenset[Signal]
) -> None:
    """Row 12 of the migration plan's declaration table, resolved.

    Derived from what `main()` reads in its own process on each placement:
    `:175` gives `SessionEnd` `tokens = None` without opening the transcript,
    and the other three fall through to `_tokens_of`.
    """
    assert builtin_signals("herdr-context-gauge", event=event) == expected
