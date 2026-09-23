# ADR-068: Profiles are identity × agent

**Status:** accepted
**Date:** 2026-09-23
**Implemented:** 2026-09-23 — `ProfileEntry.identity`, `agents.registry.PROFILE_PREFIXES`,
`core.profile_identity.{profile_identity,profile_source_dir}`, `sync_profiles`
iterating configured profiles, `lh run`/`lh exec --agent`, and `lh metrics
rename-profile` (`specs/plans/2026-09-23-profile-identity-plan.md`, Tasks 1–7).
The fleet cutover — dotfiles, `lazy-ai-tools`, `lazy-ansible`, per-host deploy —
is the design's own runbook, steps 2–7, and is out of scope for this change.
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent adapter pattern), ADR-049 (permission bypass is a
declared intent), ADR-054 (`{config_dir}` in external hooks), the 2026-09-13
multi-agent harness design (`root_default`)

## Context

A profile name encodes two facts — whose context it is and which agent runs it —
without the model separating them. The fleet's config dirs follow
`{agent}-{identity}` (`~/.claude-lazy`, `~/.codex-lazy`) while the profile names
do not (`lazy`, `lazy-codex`). The wizard derives the config dir by prefixing
the agent to the profile name, so a profile named after its agent would get the
prefix twice. The Codex profile shares the personal identity's context through
a symlink in the source tree, which the harness cannot see and a second
subscription of the same agent would have to copy again.

Design: [`2026-09-23-profile-identity-design.md`](../designs/2026-09-23-profile-identity-design.md).

## Decision

1. `ProfileEntry.identity` is an optional field; absent, the identity is the
   profile name and nothing changes. Present, the profile's name is an explicit
   TOML key validated as `{prefix}-{identity}` or `{prefix}-{identity}-{suffix}`,
   where `prefix` is declared once, in `agents.registry.PROFILE_PREFIXES`.
2. The profile source tree is organised by identity:
   `profiles/<identity>/`, resolved by a single `profile_source_dir` helper.
   Agent-specific assets live in `<identity>/<agent>/`.
3. System docs are generated per `(identity, agent)` pair, never per profile,
   and never name a concrete profile.
4. `lh run` / `lh exec` accept `--agent <prefix>`, which filters candidates
   before root resolution and never falls back to another agent's profile.
5. The rename of existing profiles is a coordinated cutover with no
   compatibility names; metrics history is rewritten to the new names.

## Consequences

- Several profiles per (agent, identity) are legal and share their context by
  construction.
- `sync_profiles` becomes profile-driven once at least one profile in the
  config declares `identity`; from then on a source directory no configured
  profile names is reported, not synced. Until then — decision 1's "nothing
  changes" — an unnamed directory keeps the pre-identity fallback of being
  synced with the caller's own adapter.
- Every consumer passing an old `--profile` value breaks at the cutover and is
  migrated in the same window.

## Alternatives considered

- **Plain rename** (`lazy` → `claude-lazy`, source dirs renamed one-to-one).
  Smaller, but keeps the symlink and the double-prefix wizard, and gives a second
  subscription no home.
- **Fully derived names** (`{prefix}-{identity}[-{slot}]`, no TOML key). A TOML
  table needs a key regardless, so the name would be written twice.
- **Required `identity`.** Breaks every existing configuration of the public
  package on upgrade for no behaviour the optional form lacks.
- **Compatibility aliases** (`previous_names`). Lets consumers migrate at their
  own pace, at the cost of resolver code and a deprecation window; rejected in
  favour of a single coordinated cutover.
