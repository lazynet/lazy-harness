"""`hook_events()` surfaced per profile: operations and event vocabulary (step 10).

`signal_gaps.py` answers one half of "a hook installs and then never does
anything useful": a signal its `TranscriptReader` cannot deliver. This module
answers the other two halves, both read off `hook_events()` and
`BuiltinHookSpec.operations` rather than a transcript:

- A hook declares an `Operation` (decision 9) that no native tool this
  adapter can emit ever carries — the hook installs, runs on every tool call,
  and the ones it was written for never arrive. `HookOperationGap`.
- A hook is wired to an event `hook_events()` carries no key for at all — the
  hook does not even install. `UncarriedEventHook`. This is the state
  `signal_gaps.gaps_for_profile` deliberately skips over (see its docstring),
  because a missing `TranscriptReader` and a missing event vocabulary are
  fixed by different mechanisms and collapsing them sends the reader after
  the wrong one.

Both read `merge_with_defaults` the same way `gaps_for_profile` does, never a
second copy of `DEFAULT_HOOKS` — the hook set one command reasons about is
answered in one place.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from lazy_harness.agents.base import AgentAdapter, Operation
from lazy_harness.core.config import Config


@dataclass(frozen=True)
class HookOperationGap:
    """One deployed hook whose declared operations this profile's agent cannot fully produce.

    `inert` names the operations absent from the adapter's own tool-name ->
    `Operation` map: no native tool call this agent can emit ever carries one,
    so a hook reasoning about it here is watching for a `ToolCall` that never
    arrives. `fully_inert` separates "some coverage lost" from "the whole hook
    can never fire meaningfully" — `pre-tool-use-read-size` on Codex is the
    second: its only declared operation is unproducible, so the hook installs,
    is asked about every tool call, and passes every one of them.
    """

    profile: str
    agent: str
    event: str
    hook: str
    inert: tuple[Operation, ...]
    fully_inert: bool


@dataclass(frozen=True)
class UncarriedEventHook:
    """One deployed hook wired to an event its profile's agent does not carry at all.

    Distinct from `HookOperationGap` and `signal_gaps.HookSignalGap`, both of
    which name a hook whose event *is* delivered but whose needs the delivery
    does not meet. Here `hook_events()` has no key for the event, so nothing
    installs and nothing runs — the fix is the agent's own event vocabulary,
    never a `TranscriptReader` or a tool-operation mapping.
    """

    profile: str
    agent: str
    event: str
    hook: str


def _producible_operations(agent: AgentAdapter) -> frozenset[Operation]:
    """Every `Operation` this adapter's own tool-name map can produce.

    Reads the adapter module's private `_TOOL_OPERATIONS`, the same read
    `tests/unit/test_hook_matcher_coverage.py`'s `_emitted_by` already makes
    and for the same reason: if the name moves, this returns the empty set and
    every declared operation reports inert, loudly, instead of a silent pass.
    An adapter with no such module (a `NullAdapter` or a test fake) also
    resolves to the empty set — the conservative answer, since no evidence
    exists that it can produce anything.
    """
    module = sys.modules.get(type(agent).__module__)
    tool_operations: dict[str, Operation] = getattr(module, "_TOOL_OPERATIONS", {})
    return frozenset(tool_operations.values())


def operation_gaps_for_profile(cfg: Config, profile: str) -> list[HookOperationGap]:
    """Every hook this profile would install whose declared operations this
    agent cannot fully produce."""
    from lazy_harness.agents.registry import agent_for_profile
    from lazy_harness.deploy.defaults import merge_with_defaults
    from lazy_harness.hooks.loader import builtin_operations

    agent = agent_for_profile(cfg, profile)
    events = agent.hook_events()
    producible = _producible_operations(agent)

    gaps: list[HookOperationGap] = []
    for event, script_names in merge_with_defaults(cfg.hooks, agent).items():
        if event not in events:
            continue
        for name in script_names:
            declared = builtin_operations(name)
            inert = declared - producible
            if not inert:
                continue
            gaps.append(
                HookOperationGap(
                    profile=profile,
                    agent=agent.name,
                    event=event,
                    hook=name,
                    inert=tuple(sorted(inert)),
                    fully_inert=not (declared & producible),
                )
            )
    return gaps


def collect_hook_operation_gaps(cfg: Config) -> list[HookOperationGap]:
    """`operation_gaps_for_profile` over every profile this config declares."""
    from lazy_harness.deploy.engine import selected_profiles

    gaps: list[HookOperationGap] = []
    for profile in selected_profiles(cfg, None):
        gaps.extend(operation_gaps_for_profile(cfg, profile))
    return gaps


def uncarried_events_for_profile(cfg: Config, profile: str) -> list[UncarriedEventHook]:
    """Every hook this profile is configured to wire to an event this agent
    does not deliver at all."""
    from lazy_harness.agents.registry import agent_for_profile
    from lazy_harness.deploy.defaults import merge_with_defaults

    agent = agent_for_profile(cfg, profile)
    events = agent.hook_events()

    gaps: list[UncarriedEventHook] = []
    for event, script_names in merge_with_defaults(cfg.hooks, agent).items():
        if event in events:
            continue
        for name in script_names:
            gaps.append(
                UncarriedEventHook(profile=profile, agent=agent.name, event=event, hook=name)
            )
    return gaps


def collect_uncarried_events(cfg: Config) -> list[UncarriedEventHook]:
    """`uncarried_events_for_profile` over every profile this config declares."""
    from lazy_harness.deploy.engine import selected_profiles

    gaps: list[UncarriedEventHook] = []
    for profile in selected_profiles(cfg, None):
        gaps.extend(uncarried_events_for_profile(cfg, profile))
    return gaps
