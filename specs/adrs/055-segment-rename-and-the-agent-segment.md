# ADR-055: Closing ADR-043's migration window — who renames the segments, and who owns the assembled doc

**Status:** accepted
**Date:** 2026-09-17
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-009 (profile symlink deploy), ADR-043 (system docs by role — opened the window this closes), ADR-052 (profile assets per agent — `lh profile migrate`)

## Context

ADR-043 renamed the system-doc segments by role — `head.md`, `_common/common.md`,
`_common/<agent>.md`, `tail.md` — and shipped a **read fallback** to the
pre-rename stem-keyed spelling (`CLAUDE.head.md`, `_common/CLAUDE.common.md`,
`CLAUDE.tail.md`). It named the fallback "a migration window, not a second
permanent answer", and said it "comes out with the chezmoi rename".

Four things were measured on 2026-09-17, on the deployed machine and in the repo,
before deciding anything here.

**The assembler already does everything ADR-043 decided.** `sync_agent_md.py`
reads both layouts, prefers the role-named one, renders
`head + common + <agent> + tail`, and reports `legacy segment layout` on the
fallback. `_common/<agent>.md` is not "new, optional and unimplemented": it is
read per profile through `agent_for_profile`, and
`tests/integration/test_profile_segments_assembler.py` already exercises a Codex
profile assembled from `_common/codex.md`.

**Nothing renames the files.** `lh profile migrate` (ADR-052) moves a profile's
root *assets* into `shared/` and per-agent segments, and explicitly leaves the
doc segments at the root — its help says "the assembled system docs and the
segments they are built from stay at the profile root". Correct about the
location, silent about the name. So the window ADR-043 opened had no command to
close it, and the only closer on offer was a hand-run `git mv` in a second
repository.

**The deployed tree is entirely on the legacy names.**
`~/.config/lazy-harness/profiles/` holds `_common/CLAUDE.common.md` and, per
profile, `CLAUDE.head.md` / `CLAUDE.md` / `CLAUDE.tail.md`. No role-named file
exists anywhere on disk. The tree is chezmoi source in another repository, and
the *assembled* `CLAUDE.md` is committed there too — so `chezmoi apply` can
re-impose a stale assembled document over one `sync-system-doc` just wrote.

**A `lazy-codex` profile is declared and has no content directory.**
`config.toml` names `[profiles.lazy-codex]` with `agent = "codex"`, and
`~/.codex-lazy/` has no `AGENTS.md`. Giving it one means adding a role-named
profile beside two legacy ones — which is where the ordering trap below lives.

## Decision

### 1. `lh profile migrate` renames the segments; nothing else does

The command that already performs the ADR-052 layout migration performs this one.
A rename is not a move — nothing changes segment — so it is a separate list on
`MigrationPlan`, a separate verb in the output (`rename` / `would rename`), and a
separate count in the summary. Under the same all-or-nothing guard: every
destination, moves and renames together, is checked before the first
`Path.rename`.

```
CLAUDE.head.md            → head.md
CLAUDE.tail.md            → tail.md
_common/CLAUDE.common.md  → _common/common.md
```

The stems come from the registry (`system_docs()`), never a typed list, for the
same reason ADR-052 gives: a hardcoded table is a second answer to a question the
adapters already answer.

**Why the same command rather than a new one.** The two migrations are the same
event for a user — "move this profile to the current layout" — and they interact:
the rename changes what the root layer carries, so the deploy that relinks after
a move is the deploy that must prune `CLAUDE.head.md` and create `head.md`. Two
commands would let a user run one and not the other, and the state in between is
the one where `chezmoi apply` and `sync-system-doc` disagree about a filename.

### 2. The shared segment waits for the last profile

`_common/` is one directory for the whole tree, and it is the only thing outside
the profile directory this command touches. A rename there while a sibling
profile is still on the legacy layout turns that sibling's next sync into
`SyncError: missing _common/CLAUDE.common.md` — and because `sync_profiles`
loads every shared segment the tree needs *before the first write*, the refusal
takes down the sync for every profile, not just the unmigrated one.

So `plan_migration` renames the shared segment only when no sibling directory
still reads it: one carrying `head.md` has migrated, one carrying only
`<stem>.head.md` has not. Read from disk rather than from `config.toml`, because
the tree can hold directories for profiles since removed from the config and
those still break the run that walks the whole tree. When it waits, it says so —
`keep _common/CLAUDE.common.md (still read by profile 'flex')`.

This is also the ordering constraint on adding `lazy-codex`: the new profile is
born role-named, so it needs `_common/common.md`, so the shared rename comes
**before** the new profile directory, not after.
`test_a_new_role_named_profile_blocks_sync_until_the_shared_segment_is_renamed`
holds that.

### 3. A legacy segment beside its role-named replacement is named, not renamed

Mid-migration a profile can carry both, and ADR-043 already decided the
role-named one wins for reading. Renaming over it would destroy the live segment,
so the leftover goes to `kept` with
`leftover — head.md is already there` and the user deletes it. Two legacy
spellings claiming one role (`CLAUDE.head.md` and `AGENTS.head.md` in one
directory) is refused whole, by name, before anything moves: neither destination
exists yet, so the overwrite guard cannot see it.

### 4. The agent segment stays shared, and stays as ADR-043 built it

No change. `_common/<agent>.md` keyed by `agent_for_profile`, one per agent for
the whole tree. What this ADR adds is the test that the key is load-bearing
across agents — a line living only in `_common/claude-code.md` must never reach a
Codex document, which is the failure that would tell a Codex worker to call
`TaskCreate`. The two segments themselves (`_common/codex.md`,
`_common/claude-code.md`) are dotfiles content, not repo content, and ship in the
user's chezmoi source.

### 5. The assembled document leaves the chezmoi source; `sync-system-doc` owns it

`CLAUDE.md` / `AGENTS.md` at the profile root is a **generated artifact**. It
carries a `GENERATED by ... — edit <segments> instead` header and the harness
version that wrote it, and the sync hook regenerates it on every segment edit.
Keeping it in the chezmoi source gives two writers one file, and the loser is
whichever ran first: `chezmoi apply` after an `lh` upgrade re-imposes a document
stamped with the old version, and nothing reports it, because both writers
succeeded.

So the assembled document is removed from the chezmoi source and ignored there.
The segments stay in chezmoi — they are hand-written input, which is exactly what
chezmoi is for. This is the same split the repo already applies to every other
generated artifact.

The cost is that a fresh machine has no assembled document until the first
`lh deploy` (which runs the sync) — acceptable, because a fresh machine has no
`lh` either until that step, and a document assembled by an absent binary would
be stale by construction.

## Alternatives

**Keep the `CLAUDE.*` names and map them in the adapter.** The fallback becomes
permanent and the layout keeps Claude Code's filename as the key for every
agent's segments — which is precisely the coupling ADR-043 removed, and it still
yields no name for a destination like `instructions/lh.instructions.md`.
Rejected: it reopens a closed decision to avoid one `git mv`.

**Per-profile agent segments (`<profile>/<agent>.md`).** Rejected again on the
same measurement ADR-043 made: every agent-specific line lives in the shared
segment and none in any profile's head or tail. One agent and zero divergent
profiles is not a pattern. The override remains additive and costs nothing to add
when a second profile needs it.

**A separate `lh profile rename-segments` command.** Rejected under decision 1 —
it makes the half-migrated state reachable by doing nothing wrong.

**Leave the assembled document in chezmoi and have sync skip an existing file.**
Rejected: it inverts the generator into a one-shot initialiser, so a segment edit
would stop changing the document, which is the whole mechanism.

## Consequences

- The deployed tree needs one ordered pass in the dotfiles repository before
  `migrate` has anything to do there; the plan lives with the user's report for
  this change, not in this repo, because it renames files in another one.
- `lh profile migrate --dry-run` now prints rename lines and a two-part summary,
  so any script parsing its output sees new lines. It is a reporting command with
  no stable machine contract, so this is a change, not a break.
- **The segments are deployed into the config dir, and that does not change
  here.** The root layer is linked whole (ADR-052), so `head.md` and `tail.md`
  arrive beside the document they build — `~/.claude-lazy/CLAUDE.head.md` exists
  today for the same reason. It is measured and asserted in
  `test_each_ledger_lists_exactly_the_links_that_profile_was_given` rather than
  quietly inherited. Excluding them is a change to `resolve_segments` with its
  own trade-off (the deploy would stop being "link the root layer"), and it is
  not this ADR's.
- The old links are pruned on the redeploy after the rename, because the ledger
  records them as harness-owned. Asserted, not assumed.

## Kill criteria

The legacy read fallback in `sync_agent_md.py` is what this ADR exists to retire.
It comes out when both deployed profiles and the chezmoi source carry only
role-named segments — verified by `lh profile sync-system-doc` reporting no
`legacy segment layout` line on either machine. Until then the fallback stays:
removing it early is the failure ADR-043 named, a contract document that silently
stops regenerating.

If the rename has not been run on the deployed tree by the release after this
one, the migration is not happening on its own and the fallback should be
promoted to the permanent answer rather than left as a window nobody closes.

## Evolution

**2026-09-18 — kill criterion closed.** The rename landed in the dotfiles
source, all three deployed profiles carried only role-named segments, and
`lh profile sync-system-doc` reported no `legacy segment layout` line. The read
fallback was therefore retired in the following PR: a legacy-only directory is
skipped and names `lh profile migrate`, while a role-named layout ignores any
legacy leftover beside it.

The sentence in §5 saying that the first `lh deploy` runs the sync was not true
when this ADR was accepted. The deploy path never called `sync_profiles`; during
the 0.73.0 upgrade all three profile documents stayed stamped 0.72.1 until a
manual `lh profile sync-system-doc` run. From this PR, deploy assembles the
documents before linking profile content, and a narrowed deploy assembles only
the selected profile.
