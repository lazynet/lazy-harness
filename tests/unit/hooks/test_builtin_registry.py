"""The builtin registry mirrors the builtins directory, entry for entry.

Both entry points resolve a builtin through this registry, so a module it does
not carry is a hook neither would ever reach — not a hook with a safe default.
The list is static and the directory is not, so completeness is asserted
against the glob rather than maintained by hand.
"""

from __future__ import annotations

import importlib
import inspect
import json
import typing
from pathlib import Path

import pytest

from lazy_harness.agents.base import HookDecision, HookEvent
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.hooks.loader import _BUILTIN_HOOKS

_SRC = Path(__file__).resolve().parents[3] / "src" / "lazy_harness"
_BUILTINS_DIR = _SRC / "hooks" / "builtins"

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


def test_every_builtin_main_takes_an_event_and_returns_a_decision() -> None:
    """The contract the single dispatch now assumes, with nothing left to route on.

    `execute_hook` and `lh hook` both call `run_hook`, which calls `main(event)`
    unconditionally. A module whose `main()` takes no argument used to be
    routed elsewhere by `BuiltinHookSpec.migrated`; with that field gone, it is
    a `TypeError` on the hook's first real invocation and nowhere earlier.

    Read off every registered module rather than checked against a literal
    list, which would only restate what `inspect.signature` can be asked
    directly.
    """
    for name, spec in _BUILTIN_HOOKS.items():
        module = importlib.import_module(spec.module)
        params = list(inspect.signature(module.main).parameters)
        assert params == ["event"], f"{name}: main{tuple(params)} does not take an event"
        hints = typing.get_type_hints(module.main)
        assert hints["event"] is HookEvent, name
        assert hints["return"] is HookDecision, name


#: Migrated builtins that deliberately declare no `event`, with the reason.
#:
#: A hook handling one event has one right fallback; a hook that branches on
#: several has none, and naming one of them would answer wrongly for an
#: operator who wired it elsewhere. The cost is real and is asserted below
#: rather than described: on the one path that carries no `hook_event_name`,
#: these hooks stop running.
EVENTLESS_BY_DESIGN = {
    "herdr-context-gauge": "branches on four events; the operator's placement decides",
}


def test_every_builtin_declares_the_event_it_is_wired_to() -> None:
    """The runner's fallback when a payload does not name one — see `loader`.

    `lh hook <name>` has no event flag, so a hook with no declared event cannot
    be parsed or serialised at all on that path. Every builtin therefore
    declares one, except those `EVENTLESS_BY_DESIGN` names and justifies.
    """
    undeclared = sorted(
        name
        for name, spec in _BUILTIN_HOOKS.items()
        if not spec.event and name not in EVENTLESS_BY_DESIGN
    )
    assert undeclared == []


def test_the_exemption_list_names_only_hooks_that_are_actually_exempt() -> None:
    """A stale entry here would license a hook that has since declared an event."""
    for name in EVENTLESS_BY_DESIGN:
        spec = _BUILTIN_HOOKS[name]
        assert spec.event is None, f"{name} declares event={spec.event!r} and needs no exemption"


@pytest.mark.parametrize("name", sorted(EVENTLESS_BY_DESIGN))
def test_an_eventless_hook_refuses_a_payload_that_names_no_event(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The declared cost of leaving `event` unset, asserted rather than assumed.

    `runner._canonical_event` consults the payload first and `spec.event` only
    when the payload is silent (`runner.py:92-94`). With both absent it does not
    fall back — it walks the adapter's event table looking for a `native_name`
    equal to `None`, finds none, and raises (`:95-98`). The non-blocking policy
    turns that into exit 0 with a stderr line, so the hook simply does not run.

    This matters to hand invocation, on two payloads that used to work and now
    do not. Before the migration both `</dev/null` and `{}` reached `main()`
    with `event = None`, and for `herdr-context-gauge` that took the clear
    branch — making `lh hook herdr-context-gauge </dev/null` the manual way to
    wipe a gauge stranded on a pane. The two now refuse at different points,
    which is why both are asserted: empty stdin never reaches the event lookup
    at all, `_parse_payload` having refused it first.

    The workaround for either is to name the event, which is also what every
    deployed invocation does:

        echo '{"hook_event_name": "SessionEnd"}' | lh hook herdr-context-gauge

    Asserted here so that a future change to the fallback cannot quietly alter
    it, and documented where an operator would look for it in
    `docs/how/hooks.md`.
    """
    from lazy_harness.hooks.runner import run_hook

    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "agent"))

    empty_stdin = run_hook(name, profile="", stdin_text="")
    no_event_named = run_hook(name, profile="", stdin_text="{}")

    assert empty_stdin.exit_code == 0
    assert "unparseable payload" in (empty_stdin.stderr or "")
    assert no_event_named.exit_code == 0
    assert "no canonical event" in (no_event_named.stderr or "")


@pytest.mark.parametrize("name", sorted(EVENTLESS_BY_DESIGN))
def test_an_eventless_hook_runs_when_the_payload_names_the_event(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: the deployed path always carries one, so it is unaffected.

    `settings.json` runs `lh hook <name> --profile <p>` and the agent pipes the
    payload, so `hook_event_name` is there on every real invocation. Without
    this assertion the one above would pass just as well against a hook that had
    stopped working entirely.
    """
    from lazy_harness.hooks.runner import run_hook

    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "agent"))

    output = run_hook(
        name,
        profile="",
        stdin_text=json.dumps({"hook_event_name": "SessionEnd", "session_id": "s1"}),
    )

    assert output.exit_code == 0
    assert output.stderr in (None, "")


def test_a_declared_event_is_one_the_agent_delivers() -> None:
    """A canonical name no adapter knows would fail only at hook time."""
    supported = set(ClaudeCodeAdapter().hook_events())
    for name, spec in _BUILTIN_HOOKS.items():
        if spec.event is not None:
            assert spec.event in supported, f"{name}: {spec.event}"


def test_no_transitional_migration_field_survives() -> None:
    """The field, the constant and the branches reading them die together.

    Asserted on the declaration rather than on behaviour: a leftover
    `migrated=True` on every spec is inert and would never fail a behavioural
    test, while still being the forked answer the design set out to remove.

    Asserted on the dataclass fields and the call graph rather than on the
    source text, because a substring check over a file passes or fails on the
    comments explaining the removal as readily as on the removal itself.
    """
    import ast
    import dataclasses

    from lazy_harness.hooks import loader as loader_module

    # The field, not the word: `"migrated" not in source` also matches the
    # prose explaining why it is gone, so it passes on a file that still
    # declares it under a comment and fails on one that merely mentions it.
    fields = {f.name for f in dataclasses.fields(loader_module.BuiltinHookSpec)}
    assert "migrated" not in fields, fields
    assert not hasattr(loader_module, "PRE_RUNNER_AGENT")
    assert not hasattr(loader_module, "builtin_migrated")

    # The dispatch, not the import: `importlib` may return to `hooks_cmd.py`
    # for an unrelated reason, and its absence would then read as proof of
    # something it never established. Assert on the call graph instead.
    tree = ast.parse((_SRC / "cli" / "hooks_cmd.py").read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "import_module" not in called, "the pre-runner dispatch still imports a builtin"


def test_the_deploy_has_no_pre_runner_warning_left_to_emit() -> None:
    """`_warn_unmigrated` outlived what it warned about, and it is not inert.

    It is called on every event of every deploy (`deploy/engine.py`), so a
    survivor is a per-profile loop over every hook computing an answer that is
    now always "nothing to say". Asserted on the module rather than on the
    absence of a line in some captured output: the warning only ever fired for
    a non-Claude-Code agent, so an output check on the default profile passes
    with the function fully intact.
    """
    from lazy_harness.deploy import engine as deploy_engine

    assert not hasattr(deploy_engine, "_warn_unmigrated")
