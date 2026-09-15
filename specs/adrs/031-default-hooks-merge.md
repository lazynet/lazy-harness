# ADR-031: Default hooks merge layer in `lh deploy`

**Status:** accepted
**Date:** 2026-05-21
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-006 (hooks as subprocess), ADR-009 (profile symlink deploy)

## Context

Through ADR-006 + ADR-009 the framework deploys hooks by translating
`[hooks.<event>]` blocks from `config.toml` into per-profile
`settings.json` entries. The implementation in `deploy/engine.py` was
`settings["hooks"] = agent_hooks`, where `agent_hooks` is generated only
from events the user explicitly declared in `config.toml`.

Two operational failures followed:

1. A user who added a partial `[hooks.*]` block to their `config.toml`
   (e.g. just `pre_tool_use` for the security cluster) silently lost
   every previously-deployed hook for the events they did not declare.
   This was the real incident on 2026-04-17: pasting two `[hooks.*]`
   sections wiped `SessionStart` (`context-inject`), `Stop`
   (`session-export` + `compound-loop`), and `PreCompact` (`pre-compact`)
   from a profile that had been working for months.
2. `lh init` ships `templates/config.toml.default` with zero
   `[hooks.*]` blocks, so a fresh install deployed a profile with no
   hooks at all. The README advertised "session-start context injection,
   pre-compact summaries, session export and compound-loop enforcement"
   as out-of-the-box behavior, but none of it fired until the user
   copied hook declarations from the docs by hand.

The framework conflated "user override" with "complete set". They are
not the same thing.

## Decision

The framework owns a Python-literal `DEFAULT_HOOKS` map in
`src/lazy_harness/deploy/defaults.py`. `lh deploy` computes the
effective per-event script list as

    effective[event] =
        user_hooks[event].scripts if event in user_hooks
        else DEFAULT_HOOKS[event]

User declarations override per-event (`scripts = []` is an explicit
opt-out for that event). Events present in `user_hooks` but absent from
`DEFAULT_HOOKS` (custom events) pass through verbatim. The
`settings.json` `hooks` block is wholly framework-owned: on every
deploy, the engine diffs the existing block against the new effective
block and, when it finds command strings that no longer appear, writes
`settings.json.bak` and logs a warning naming the removed commands. No
chain of backups is kept — the user is expected to version-control
`~/.config/lazy-harness/` if they want a longer history.

This work also surfaced a pre-existing bug in `ClaudeCodeAdapter`: the
`hook_event_map` was missing `post_compact → PostCompact`, so the
`post-compact` built-in never actually wired into `settings.json` even
when declared. Fixed alongside the default-set work.

## Alternatives considered

- **Keep `cfg.hooks` as the complete set, document harder.** Rejected.
  The README and the docs site already documented the built-ins as
  out-of-the-box; aligning behavior with documentation is cheaper than
  rewriting both. The 2026-04-17 incident also shows that "remember to
  declare every hook you want" is a tripwire, not a feature.
- **Preserve unknown entries in `settings.json`.** Rejected. Breaks the
  idempotency contract — the output of `lh deploy` would depend on
  whatever happened to be in `settings.json` previously, including drift
  from prior framework versions. The backup + warning gives users the
  data they need without compromising idempotency.
- **Per-script override granularity (`scripts_disabled = [...]`).**
  Rejected. The smallest stable override unit is one event. Per-script
  disables would force the framework to version the default *set* so a
  rename or replacement could be expressed; one event keeps the API
  surface flat. Users who want fine control re-list the event with the
  subset they want.
- **TOML-embedded default set in the package.** Rejected. Adds parsing
  cost on every deploy, requires a new resource-loading step, and gains
  nothing over a Python literal for a list this small. A future
  `lh config show-defaults` command can print the dict in TOML form
  without changing the source-of-truth representation.

## Consequences

- Fresh installs deploy the built-in hooks automatically. The README's
  out-of-the-box promise is now true.
- The 2026-04-17 failure mode is gone: a partial `[hooks.*]` config can
  no longer strip undeclared events.
- Users who want to suppress a built-in must opt-out per-event with
  `scripts = []` or override the event explicitly. There is no
  per-script disable.
- When a future release adds a new entry to `DEFAULT_HOOKS[event]`,
  users who did not declare that event get it automatically on the next
  `lh deploy`. Users who did declare the event keep their list
  unchanged.
- Hand-edits to the `hooks` block in `settings.json` no longer survive a
  deploy. They surface as a warning per command with a backup for
  forensic recovery, but the canonical path is to declare the hook
  through `config.toml` or `~/.config/lazy-harness/hooks/`.
- `post-compact` built-in now actually wires through `lh deploy`. Users
  on older deploys who relied on it being a no-op may see the hook fire
  for the first time on their next `lh deploy`; behaviour is fail-soft.

## Evolution

**2026-09-15 (0.67.0, PR #295): the effective set is no longer the merge.**
The formula under **Decision** still describes the merge, but the merge is now
the first of two stages, not the whole answer. `_hook_entries_for`
(`deploy/engine.py`) computes `effective` exactly as written above and then
drops every script whose declared `Signal`s the *profile's agent* cannot
deliver, asking `gaps_for_profile` (`hooks/signal_gaps.py`) — the same reader
`lh doctor` reports from, so the two cannot drift. The effective set is
therefore

    entries[event] = [
        script for script in effective[event]
        if (event, script) not in gaps_for_profile(cfg, profile)
    ]

This narrows an override, which the original decision did not contemplate: a
user who declares `stop-verify-guard` explicitly in
`[hooks.session_stop].scripts` does **not** get it deployed on an agent that
supplies no `GOAL_STATUS`. "User declarations override per-event" now means
they override the *defaults*, not the agent's capabilities.

What keeps this from being a silent drop — the failure mode this ADR exists to
prevent — is that the omission is printed, by name and with its reason:

    · stop-verify-guard omitted in 'throwaway': agent 'codex' does not deliver goal_status

That is the whole distinction from the 2026-04-17 incident. There the hooks
vanished from a deployed profile with no output at all; here the deploy names
every hook it left out and why, on the run that leaves it out. The alternative
was worse than either: `stop-verify-guard` deployed to an agent with no goal
marker finds nothing to verify, concludes there is nothing to do and passes —
green because it cannot fail. `BuiltinHookSpec.signals` exists so that a hook
which cannot work is refused rather than trusted.

See [ADR-041](041-multi-agent-hook-contract.md) property 2 for the contract this
implements.

## Implementation

Tracked in `specs/plans/2026-05-21-deploy-hook-defaults-plan.md` and
delivered in the same PR as this ADR.
