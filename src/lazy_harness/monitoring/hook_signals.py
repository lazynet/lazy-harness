"""Signals a profile's deployed hooks need and its agent cannot deliver.

Step 4 of `specs/designs/2026-09-13-multi-agent-harness-design.md` needs a
`lh doctor` line that names a hook's missing signals — without it the contract
gate cannot observe why `stop-verify-guard` is inert on an agent that supplies
no `GOAL_STATUS`, and a gate that cannot observe its own subject is not a gate.

Deliberately *not* the `hook_events()` surface (honoured verdicts per event,
operations covered per hook), which is step 10.
"""

from __future__ import annotations

from dataclasses import dataclass

from lazy_harness.agents.base import Signal
from lazy_harness.core.config import Config


@dataclass(frozen=True)
class HookSignalGap:
    """One deployed hook whose declared signals its profile's agent lacks.

    `has_reader` separates the two ways an agent arrives here — no
    `TranscriptReader` at all, versus one whose vocabulary is narrower than the
    hook's — because only the second is fixed by extending an existing reader.
    """

    profile: str
    agent: str
    event: str
    hook: str
    missing: tuple[Signal, ...]
    has_reader: bool


def collect_hook_signal_gaps(cfg: Config) -> list[HookSignalGap]:
    """Every (profile, hook) pair that would install and then never fire.

    A hook is "deployed" here by the same resolution the deploy path uses —
    `selected_profiles` and `merge_with_defaults` — rather than by re-reading
    `DEFAULT_HOOKS`, so doctor cannot report on a hook set deploy would not
    write.

    **Events the agent does not deliver are skipped, not reported as missing
    signals.** The design calls these two distinct states and refuses to
    collapse them: an absent `hook_events()` key means nothing is installed and
    nothing runs, which waits on the agent's event vocabulary, while a present
    key with an undeliverable signal means the hook installs, runs, finds
    nothing and passes, which waits on a `TranscriptReader`. Surfacing the
    first is step 10's `hook_events()` line; this collector answers only the
    second, and says so rather than guessing.
    """
    from lazy_harness.agents.registry import agent_for_profile
    from lazy_harness.deploy.defaults import merge_with_defaults
    from lazy_harness.deploy.engine import selected_profiles
    from lazy_harness.hooks.builtins._shared import transcript_reader
    from lazy_harness.hooks.loader import builtin_signals

    gaps: list[HookSignalGap] = []
    for profile in selected_profiles(cfg, None):
        adapter = agent_for_profile(cfg, profile)
        reader = transcript_reader(profile, cfg)
        delivered = reader.signals() if reader is not None else set()
        events = adapter.hook_events()

        for event, script_names in merge_with_defaults(cfg.hooks, adapter).items():
            if event not in events:
                continue
            for name in script_names:
                missing = builtin_signals(name) - delivered
                if not missing:
                    continue
                gaps.append(
                    HookSignalGap(
                        profile=profile,
                        agent=adapter.name,
                        event=event,
                        hook=name,
                        missing=tuple(sorted(missing)),
                        has_reader=reader is not None,
                    )
                )
    return gaps
