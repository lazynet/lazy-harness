# ADR-063: The hook ownership ledger — its own document, keyed by identity

**Status:** accepted
**Date:** 2026-09-20
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-031 (default hooks merge), ADR-042 (multi-file config planning),
ADR-052 (profile assets per agent), ADR-064 (settings shape gate)

## Context

`ClaudeCodeAdapter` merges its generated hook groups over whatever is already in
a profile's `settings.json`, so it needs a record of which groups are its own:
without one, a foreign entry is either overwritten or promoted to harness-owned.
That record — a `managed` list of `{event, index, group}` — was written into the
same document, under a top-level `lh_hook_ownership` key.

Two defects surfaced together on 2026-09-20.

**The record's shape was fatal to the reader.** A ledger entry *is* a
`{"matcher": ..., "hooks": [...]}` object by construction, which puts one three
levels below a top-level key. Claude Code 2.1.278 scans every top-level key it
does not recognise to that depth for anything hook-group shaped and discards the
**entire file** when it finds one — no hooks, no permissions, no `env`, no
`statusLine`. Every `lh deploy` that touched a profile therefore disarmed it, and
exited 0 doing so. Both Claude profiles ran that way for about nine hours before
anyone noticed; the docstring on `SettingsShapeError` records the duration.

**The record's key was positional.** A recorded position was claimed only when
`existing[event][index] == group` held — the stored index, plus byte equality of
the whole group. An external writer inserting or removing an entry earlier in the
same event's list shifts every index after it, and then the harness owns nothing:
its own groups read as foreign, are preserved rather than refreshed, and the next
deploy appends duplicates beside them.

## Decision

**The ledger lives in its own document, `lh-hook-ownership.json`, beside
`settings.json`.** It joins `config_targets()`, so ADR-042's read-plan-apply
cycle stamps and refuses it like any other target and `deploy/snapshot.py` picks
it up for rollback without being told. `_HOOK_OWNERSHIP_KEY` survives only to
recognise a ledger a pre-fix deploy embedded: `_plan_settings` pops it
unconditionally — so it is never written back whatever follows — and reads it as
this deploy's ledger only when no sidecar has taken over yet. The tri-state is
preserved across the move: absent is `None`, present-but-unusable is `{}`, and a
valid envelope is the recorded positions.

**A group is claimed by identity, not by position or by equality.**
`_hook_group_identity` — `(event, matcher, tuple of (type, command))`, already in
the codebase since #412 — becomes what the ledger is matched on. The stored index
is demoted from key to hint: it is tried first, and on a miss the event's list is
scanned for the first unclaimed entry of the same identity. The ledger format
stays at version 1, because nothing about what is stored changed, only what it is
compared against.

**The detector is ported, not inferred.** Claude Code 2.1.278's own
`gf`/`uW`/`rue`/`r7`/`zs` functions were decompiled from the shipped binary into
`agents/_settings_shape.py`, and every `settings.json` the harness generates,
goldens included, is asserted clean against it.

## Alternatives considered

**Keep the ledger in `settings.json` under a name the detector tolerates.**
Rejected. The rule is the shape three levels down, not the key's name, so any
spelling of a `matcher`+`hooks` record trips it. Flattening the record to dodge
the scan would make its format hostage to an undocumented heuristic in a binary
that upgrades on its own schedule.

**Encode the ledger as an opaque string inside `settings.json`.** Rejected: it
hides the one document an operator needs to read when a merge goes wrong, to buy
back a file the harness does not have to own anyway.

**Bump the ledger to version 2 for the identity change.** Rejected. A version
bump is for a change in what is *written*; a v1 ledger is read correctly by the
new matcher and a v1 ledger written by the new code is read correctly by the old
one. Bumping would have discarded every existing ledger to express nothing.

**Unify the layers so the ledger and the settings sit in one place.** The sidecar
is a plain file in the target dir while `settings.json` is a symlink into the
repo layer (ADR-009's Evolution), which is a real asymmetry and was logged as a
debt. Identity retires it rather than paying it: a stale index is now inert, so
the two documents no longer have to move together to stay consistent.

## Consequences

- A deploy no longer disarms the profile it deploys to. ADR-064 is the standing
  gate that keeps it that way.
- An external insert or delete in a hook list no longer costs the harness its
  claim, which is what stopped the duplicate-on-next-deploy path.
- Identity is deliberately narrower than equality: a foreign edit to a field
  *outside* `(matcher, type, command)` — a `timeout`, say — leaves the group ours,
  and the next deploy overwrites that edit. That is the trade taken, and it is the
  direction that fails safe for the harness's own hooks rather than for a
  hand-edit of a generated file.
- One more file lands in each Claude profile's config dir, stat'd twice per
  deploy like its siblings.
