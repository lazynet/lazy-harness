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
    if declared and profile not in declared:
        raise RunnerError(f"unknown profile {profile!r}; declared: {sorted(declared)}")
    return get_agent(cfg.agent.type)


def _canonical_event(adapter: AgentAdapter, payload: dict) -> str:
    native = payload.get("hook_event_name")
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
    try:
        payload = json.loads(stdin_text)
    except json.JSONDecodeError as exc:
        raise RunnerError(f"unparseable payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise RunnerError(f"unparseable payload: expected an object, got {type(payload).__name__}")
    return payload


def resolve_profile(explicit: str | None) -> str:
    """The one answer to "which profile is this hook running under".

    `--profile` is optional for as long as deployed commands predate it: the
    agent's settings file says `lh hook <name>` today and `deploy` does not
    rewrite it in this step, so requiring the flag would break every installed
    hook between one step and the next. When it is absent both entry points
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
            _canonical_event(adapter, payload), payload, profile=profile
        )
        decision = _load_main(spec.module)(event)
        return adapter.format_hook_output(event, decision)
    except Exception as exc:  # noqa: BLE001 — the policy below is the whole point
        reason = str(exc) if isinstance(exc, RunnerError) else f"{type(exc).__name__}: {exc}"
        if spec.blocking:
            return HookOutput(stdout=None, stderr=f"{name}: {reason}", exit_code=2)
        return HookOutput(stdout=None, stderr=f"{name}: {reason}", exit_code=0)
