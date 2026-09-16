"""Which of a profile's hooks declare a signal its agent cannot deliver.

The one importable answer, because two callers act on it and they must not
disagree. `lh doctor` *reports* the gap; `deploy.engine` *acts* on it by leaving
the hook out of the generated config. Re-deriving the same rule on the deploy
side would satisfy the first release and drift on the second: a hook doctor
swore was absent would appear in `settings.json`, or the reverse, and neither
half would look wrong on its own.

This module used to be `monitoring/hook_signals.py`, which was the right home
while doctor was the only reader. It moved here when deploy became the second,
so that neither the reporting side nor the enforcing side owns the rule.

Deliberately *not* the `hook_events()` surface (honoured verdicts per event,
operations covered per hook), which is step 10.
"""

from __future__ import annotations

from dataclasses import dataclass

from lazy_harness.agents.base import Signal
from lazy_harness.core.config import Config


@dataclass(frozen=True)
class HookSignalGap:
    """One hook whose declared signals its profile's agent lacks.

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


def gaps_for_profile(cfg: Config, profile: str) -> list[HookSignalGap]:
    """Every hook this profile would install that could then never fire.

    The hook set is resolved by `merge_with_defaults`, the same call the deploy
    path makes, rather than by re-reading `DEFAULT_HOOKS` — so neither caller
    can reason about a hook set deploy would not write.

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
    from lazy_harness.hooks.builtins._shared import transcript_reader
    from lazy_harness.hooks.loader import builtin_signals

    adapter = agent_for_profile(cfg, profile)
    reader = transcript_reader(profile, cfg)
    delivered = reader.signals() if reader is not None else set()
    events = adapter.hook_events()

    gaps: list[HookSignalGap] = []
    for event, script_names in merge_with_defaults(cfg.hooks, adapter).items():
        if event not in events:
            continue
        for name in script_names:
            missing = builtin_signals(name, event=event) - delivered
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


def collect_hook_signal_gaps(cfg: Config) -> list[HookSignalGap]:
    """`gaps_for_profile` over every profile this config declares.

    Narrowed through `selected_profiles` for the same reason the deploy loops
    are: the profile set one command reasons about is answered in one place.
    """
    from lazy_harness.deploy.engine import selected_profiles

    gaps: list[HookSignalGap] = []
    for profile in selected_profiles(cfg, None):
        gaps.extend(gaps_for_profile(cfg, profile))
    return gaps
