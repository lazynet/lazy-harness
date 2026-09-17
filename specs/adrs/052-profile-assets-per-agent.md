# ADR-052: Profile assets are deployed per agent — segments, file-level links, an ownership ledger

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent adapter pattern), ADR-042 (multi-file config planning), ADR-043 (system docs by role), ADR-046 (delete is not an edit — `WriteOp`'s delete case), ADR-047 (`CopilotAdapter`)

## Context

`deploy_profiles` symlinked **every entry** of `profiles/<p>/` into the profile's
config dir, unfiltered. With one agent that is correct. With a profiles tree that
holds `CLAUDE.md`, `AGENTS.md`, Claude-shaped slash commands and Copilot
`*.instructions.md`, it deploys all of them to all agents: a Codex profile
receives Claude Code's `settings.json`, and a Claude profile receives Codex's
`hooks.json`.

Decision 6 of the 2026-09-13 multi-agent design defined what the *system
document* assembles into. Nothing defined which of the remaining assets belong to
whom. This is decision 10 of that design, and the four questions its migration
raises are the decision rather than its implementation.

The tree this ships against is flat and legacy-named: `profiles/{lazy,flex}/`
hold `CLAUDE.head.md CLAUDE.md CLAUDE.tail.md commands/ docs/ settings.json
skills/`, plus `profiles/_common/CLAUDE.common.md`. No `shared/`, no `head.md`.

## Decision

### 1. Three ordered layers, not two

The profile source is read lowest precedence first: the **root**, then
`shared/`, then the directory named by `agent_for_profile(cfg, name)`. The agent
directory names come from `list_agents()`, never from a list typed into the
deployer, so a new adapter brings its segment name with it.

Modelling the root as a *layer* rather than as a special case is what makes the
migration optional. A profile with neither `shared/` nor an agent directory has
exactly one layer, so every name appears once and is linked whole — the
pre-segment behaviour, reached by the same code path rather than by a branch
guarding it. Nobody is required to migrate to keep a working profile.

Another agent's segment is excluded from the root layer by the same set that
recognises it, so it is neither deployed as its own directory nor deployed as a
stray root entry.

### 2. File-level linking, and only where it is needed

`ensure_symlink` links whole directories, so a second link **replaces** the
first rather than merging into it. `shared/skills/` and `codex/skills/` is the
normal case, not the edge one, so a name carried by more than one layer is
walked and its files linked individually.

A name carried by only **one** layer is still linked whole. Walking it would
cost an inode per file and produce the same tree; `docs/` present only in
`shared/` arrives as a single `docs/` symlink. Both shapes are tested, because
"same result" is the claim that makes the optimisation safe.

On a same-name file the higher layer wins — agent over shared over root — and
the deploy prints one line naming winner and shadowed source. The resolver
returns collisions as **data**; printing is the deployer's, since the resolver
cannot know whether its caller is `lh deploy` or a test, and a collision resolved
in silence is indistinguishable from an asset the user never had.

### 3. Deploy owns its links, and adopts on the first run

`ensure_symlink` reports an existing link and moves on, which is right for a link
about to be rewritten and wrong for one the harness has stopped generating. A
stale link from the flat layout would otherwise survive forever.

Deploy writes the set of links it created to `<config_dir>/.lazy-harness/links.json`
and, on the next run, removes the owned links it no longer generates. The path is
deliberately outside the agent's own namespace: a Claude Code config dir is
Claude Code's, and a harness file under a name the agent may one day claim is a
collision waiting to happen. This is ADR-046's delete case applied to symlinks —
a harness that cannot say *I no longer produce this* can only ever add.

**The first run has no ledger.** Rather than own nothing and strand the entire
flat layout, deploy adopts every symlink in the config dir that resolves under
that profile's source — those are the harness's by construction, since nothing
else writes links into `profiles/<p>/` — and says so once in its output.

Two things are never touched: a name the ledger does not record, whatever it
points at, and a recorded name that no longer points into the profile source,
because the user has repointed it since. The ledger records a name, not a
standing claim on it.

A ledger that is missing or unparseable reads as **absent**, not as empty.
Re-adopting is recoverable; reading junk as "owns nothing" strands every link
ever written. `None` and `set()` are therefore different answers and the caller
acts on the difference.

Pruning runs **before** linking. A name that was a whole-directory link and is
now split across files has to stop being a link first: `mkdir(exist_ok=True)`
succeeds on a symlink to a directory, so writing `skills/a.md` through the
surviving link would create it inside `profiles/<p>/` — the deployer editing its
own input. `_clear_linked_parents` guards the same hazard for a tree the ledger
never saw.

### 4. `lh profile migrate <profile> [--dry-run]`, with the registry as its oracle

An entry an adapter names in `config_targets()` goes to that agent's segment —
`settings.json` and `.claude.json` to `claude-code/`, `hooks.json` and
`config.toml` to `codex/`, the `hooks/` directory to `copilot/` via its nested
target's first path component. Everything the registry does not claim goes to
`shared/`.

The oracle is the registry because a hardcoded table would be a second answer to
a question the adapters already answer, and would go stale the first time an
adapter gained a file. No two adapters name the same entry today; if two ever
do, registration order decides and the printed plan names the winner.

**The assembled system docs and their segments stay at the profile root**, even
though `system_docs()` names them. `sync_agent_md` reads `head.md` / `tail.md`
at the root and writes the assembled document there, so moving either into a
segment would leave the assembler writing to a path the deploy no longer links.
`system_docs()` is therefore read here as a **root marker** rather than as an
ownership one — the reading that keeps decision 5 true. The legacy
`CLAUDE.head.md` spellings are recognised alongside the role-named ones.

`_common/` and anything else `_`-prefixed is never touched: it is shared across
profiles and belongs to no single segment.

Every destination is checked before the first rename, and a move that would
overwrite is refused naming the file. A migration stopped halfway leaves the
profile split across two layouts with no record of where the boundary fell —
worse than not having run. `--dry-run` moves nothing, the plan prints what stays
as well as what moves, and a second run is a no-op.

### 5. The assembler and the deployer agree, asserted through the engine

Because the doc segments and the assembled documents stay at the root, and root
entries keep deploying, `sync_agent_md` needs no change: `_Layout` finds its
segments where it always did. `segment_filenames()` and `_trees_touched` gate on
a basename and a walk up to the `profiles` directory, neither of which a
`shared/` directory between them disturbs.

That is asserted rather than reasoned: an integration test migrates, assembles,
deploys, edits `head.md` and fires the real `post-tool-use-sync-system-doc`,
then reads the **deployed** path and finds the regenerated content.

### 6. `snapshot_targets` derives from the same resolver

The rollback surface answered "which paths does a deploy own" by listing the
profile source itself. After segments that mirror targets `shared` and `codex` —
directories the deploy never links — and misses every file link inside them. It
now calls `resolve_segments`, the same function the deploy calls, and carries
the ledger: restoring links without the record of them leaves the next deploy
unable to retract any of them.

## Consequences

**A Codex profile stops receiving Claude Code's assets, and the reverse — but
only once migrated.** An unmigrated profile still deploys its root to whatever
agent it runs, which is the compatibility decision 1 buys and also the reason
the defect persists until the user acts. `lh profile migrate --dry-run` is the
only thing that tells them what would move.

**The first deploy after this ships prints an adoption line for every profile.**
It is a one-time line, and a deploy that prints it twice for the same profile
means the ledger is not being written — worth treating as a defect report rather
than as noise.

**A file link is one inode per file where a directory link was one per
directory.** A profile with a large `shared/skills/` also carried by its agent
segment will hold hundreds of links instead of one. This is the cost of merging
and it is paid only by names carried by more than one layer.

**`.lazy-harness/links.json` is a new file in every profile's config dir**, and
it is snapshot-covered, so `lh deploy --rollback` restores it with the links it
describes. A user who deletes it loses nothing: the next deploy re-adopts.

**An empty directory can be left behind by a prune.** Removing the last owned
link under `skills/` leaves an empty real `skills/` in the config dir. It is
harmless and it is not cleaned up, because deciding that a directory is the
harness's to remove needs a claim the ledger does not make.

**A migrated profile is a chezmoi diff.** The profiles tree is chezmoi source on
the machine this ships for, so `migrate` moves files chezmoi manages and the
source has to be re-added afterwards. `migrate` does not do it, and does not
know it should — the harness has no chezmoi dependency and this ADR does not
add one.

**`settings.json.bak` and similar strays route to `shared/`.** Nothing claims
them, so they follow the default. They already deployed to every agent under the
flat layout, so this is not a regression, but a migration is a good moment to
delete them rather than segment them.

## Alternatives considered

**Two layers — `shared/` and `<agent>/` only, with the root deprecated.** The
cleaner model, and it was rejected on the migration cost it forces: every
existing profile stops deploying until its owner migrates, and the assembled
system doc has nowhere to live that both the assembler and the deployer agree
on without moving `sync_agent_md` too. Three layers makes migration opt-in and
keeps the assembler untouched.

**Merge directories by copying rather than linking.** Removes the collision
question entirely — a merged directory of real files has one obvious content.
Rejected because the profile source is the editable copy: a user editing
`~/.claude/skills/a.md` expects to be editing `profiles/lazy/shared/skills/a.md`,
and copying silently breaks that round trip, which is the property the whole
symlink design exists for.

**Record ownership with a marker inside each link's target, or by naming
convention.** A symlink carries no metadata of its own, so the marker would have
to live in the source file, which the user owns and edits. A ledger next to the
links keeps the record on the side that created them. ADR-047 made the opposite
call for Copilot's hook document — ownership is the filename there — because a
glob gave it a path to own; symlinks scattered through a config dir give no such
handle.

**Prune by scanning for links into the profile source on every deploy, with no
ledger at all.** This is exactly what adoption does once, and it is wrong as a
steady state: a link the user made by hand into the profile source is
indistinguishable from one the harness wrote, so every deploy would claim and
eventually remove it. The ledger exists to make "I created this" a recorded fact
rather than an inference.
