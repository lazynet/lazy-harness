"""The hook runner: one path from stdin to the three channels an agent reads.

Every builtin used to parse Claude Code's payload itself, decide, and serialise
Claude Code's JSON itself — eighteen copies of one agent's wire format. Here the
adapter owns both translations and the builtin sees only `HookEvent` and returns
only `HookDecision`, so a second agent costs an adapter rather than eighteen
edits.

The failure policy is declared per class of failure rather than left to a
trailing `sys.exit(0)`, which is what `cli/hooks_cmd.py` did: a blocking hook
that cannot run must refuse, because exiting 0 with no output is how a caller
says "no objection" — and a security guard that fails open reports success while
the command runs.
"""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING

from lazy_harness.agents.base import HookOutput
from lazy_harness.hooks.loader import _BUILTIN_HOOKS

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from collections.abc import Callable

    from lazy_harness.agents.base import AgentAdapter, HookDecision, HookEvent


class RunnerError(Exception):
    """A failure the runner resolves against its policy rather than raising."""


def _adapter_for(profile: str) -> AgentAdapter:
    """Resolve the adapter that owns this profile's wire format.

    Per-profile agents arrive with `agent_for_profile()`; until then the
    configured agent is global and the profile is validated against the config
    so that a typo in a deployed command is a named failure rather than a hook
    that runs under the wrong scope.
    """
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.config import Config, ConfigError, load_config
    from lazy_harness.core.paths import config_file

    try:
        cfg = load_config(config_file())
    except ConfigError:
        # No config at all is a machine that has not run `lh init` -- the same
        # state as an empty profile table, and for the same reason not a
        # refusal: the hook still has an agent whose wire format it can speak.
        cfg = Config()
    declared = cfg.profiles.items
    # An empty table is a machine that has not run `lh init`, not a wrong
    # profile: refusing there would take every hook down with it.
    #
    # An unresolved profile is the same case for the same reason, and it is
    # reachable on a fully configured machine: `resolve_profile(None)` falls
    # back to `profile_name()`, which returns "" whenever the agent's config
    # dir variable is unset or names a directory no profile declares. Refusing
    # an empty profile against a populated table would take every hook down
    # with it on exactly the machines that did run `lh init`.
    #
    # A *named* profile absent from the table stays a refusal: that is a typo
    # in a deployed command, and a hook running under the wrong scope writes
    # its memory and its metrics somewhere the profile does not own.
    if profile and declared and profile not in declared:
        raise RunnerError(f"unknown profile {profile!r}; declared: {sorted(declared)}")
    return get_agent(cfg.agent.type)


def _canonical_event(adapter: AgentAdapter, payload: dict, declared: str | None) -> str:
    """Canonical event for this invocation: the payload first, the registry next.

    A payload that names an event decides, including when the name is one this
    adapter does not deliver -- that is a typo or a version skew, and resolving
    it to the hook's wiring would hide it. A payload that names none is the
    ordinary case on two live paths: `lh hook <name>` has no event flag, and
    `lh hooks run` hands over `{}`. There the registry answers, because the
    event a builtin is wired to is static.
    """
    native = payload.get("hook_event_name")
    if native is None and declared:
        return declared
    for canonical, support in adapter.hook_events().items():
        if support.native_name == native:
            return canonical
    raise RunnerError(f"no canonical event for {native!r} on {adapter.name}")


def _load_main(module_path: str) -> Callable[[HookEvent], HookDecision]:
    module = importlib.import_module(module_path)
    main_fn = getattr(module, "main", None)
    if main_fn is None:
        raise RunnerError(f"{module_path} has no main()")
    return main_fn


def _parse_payload(stdin_text: str) -> dict:
    """The payload as an object, or a failure the policy in `run_hook` resolves.

    Empty stdin, whitespace, bytes that are not JSON, and JSON that parses into
    something other than an object are one class: the runner has no payload it
    can hand a builtin. Decision 3's table puts that class in a single row —
    exit 2 for a blocking hook, exit 0 with a warning for an informational one —
    because a blocking hook that cannot run must refuse, and exiting 0 with no
    output is how a caller says "no objection".

    Degrading to `{}` instead is a change of behaviour on the shipped hooks, not
    an accident of the migration: each one used to read stdin through a helper
    that returned `{}` here, and the byte goldens froze what it then decided. A
    guard handed `{}` sees no tool call and abstains, which on the wire is
    indistinguishable from having looked. Decision 3 trades that silence for a
    named refusal deliberately.

    (`lh hooks run` handing over `{}` is not an argument either way: `{}` is a
    parsed object and never reaches this path.)
    """
    try:
        payload = json.loads(stdin_text)
    except json.JSONDecodeError as exc:
        raise RunnerError(f"unparseable payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise RunnerError(f"unparseable payload: expected an object, got {type(payload).__name__}")
    return payload


def resolve_profile(explicit: str | None) -> str:
    """The one answer to "which profile is this hook running under".

    `--profile` is optional for as long as deployed commands predate it:
    `hook_command` emits the flag, but a settings file written before it does
    not carry it until the next `lh deploy`, so requiring the flag would break
    every installed hook in between. When it is absent both entry points
    fall back to the resolution the builtins already do for themselves, in one
    place — two resolutions would be two answers to a question the memory scope
    and the metrics label both depend on.
    """
    if explicit:
        return explicit
    from lazy_harness.hooks.builtins._shared import profile_name

    return profile_name()


def run_hook(name: str, *, profile: str, stdin_text: str) -> HookOutput:
    """Run one builtin end to end and return what to write on each channel.

    Returns rather than exits so both entry points — the deployed `lh hook` and
    `lh hooks run` — share one execution mechanism instead of two.
    """
    spec = _BUILTIN_HOOKS.get(name)
    if spec is None:
        # Nothing is known about an unregistered name, including whether it
        # blocks; refusing on a guess would block tool calls a typo in
        # settings.json should merely make noisy.
        return HookOutput(stdout=None, stderr=f"Unknown hook: {name}", exit_code=0)

    try:
        adapter = _adapter_for(profile)
        payload = _parse_payload(stdin_text)
        event = adapter.parse_hook_input(
            _canonical_event(adapter, payload, spec.event), payload, profile=profile
        )
        decision = _load_main(spec.module)(event)
        return adapter.format_hook_output(event, decision)
    except Exception as exc:  # noqa: BLE001 — the policy below is the whole point
        reason = str(exc) if isinstance(exc, RunnerError) else f"{type(exc).__name__}: {exc}"
        if spec.blocking:
            return HookOutput(stdout=None, stderr=f"{name}: {reason}", exit_code=2)
        return HookOutput(stdout=None, stderr=f"{name}: {reason}", exit_code=0)
