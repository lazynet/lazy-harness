# ADR-040: Reconcile and Decay — the two missing memory-pipeline stages

**Status:** accepted
**Date:** 2026-09-10
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-027 (memory-stack-overview), ADR-030 (memory-stack-glue-layer),
ADR-029 (engram-persist-deterministic-mirror)

## Context

A five-stage model for agent memory — Capture, Consolidate, Retrieve, Reconcile, Decay — names two stages this harness never built. ADR-027's five-layer model and ADR-030's glue layer cover Capture (the compound-loop worker filters what reaches `decisions.jsonl`/`failures.jsonl`/`learnings/`), Consolidate (`lh memory consolidate` proposes `MEMORY.md` additions), and Retrieve (QMD/Engram/Graphify surfacing in `context_inject`). Nothing reconciles a contradiction, and nothing decays.

A review of the knowledge store on 2026-09-10 confirmed the gap is not theoretical:

- **Decay:** `learnings/` holds 5954 files, every one `status: active`. The oldest is from 2026-03; 5954 files have accumulated over six months and none has ever aged out. The frontmatter already carries `deprecated_by`/`deprecated_on`/`deprecated_reason`, written as `null` by `compound_loop.py` on every learning since the store's inception — the slots exist, nothing has ever filled them.
- **Reconcile:** `memory/<host>/<org>/<repo>/decisions.jsonl` has been rewritten in place at least twice without migrating old rows. `lazy-ansible/decisions.jsonl` (711 lines) has three field sets: 1 line carries `date`/`decision`/`rationale`/`alternatives` (the oldest shape), 6 carry `alternatives`/`decision`/`rationale`/`ts` (timestamp renamed, `decision` not yet renamed), and 704 carry the current `alternatives`/`context`/`project`/`rationale`/`summary`/`tags`/`ts`/`type`. A consumer reading `d["summary"]` silently drops the 7 old lines; nothing has ever reported that they exist.

Neither gap can be closed by guessing. Silently picking one schema or one "current" fact is the exact failure the source article warns against: a system that resolves ambiguity without surfacing it acts confidently on the wrong data. This ADR proposes only that Reconcile and Decay *report and mark*, never that they resolve or delete.

## Decision

Add two `lh memory` subcommands, both following the shape `lh memory consolidate` already established: read-only by default, one explicit escape hatch where a write is safe, and no LLM call unless the caller opts in.

### `lh memory decay`

Marks a learning `status: superseded` when it is still `active` and its `origin_session` is at least `--horizon-days` old (default 90). Nothing in the harness logs when a learning is retrieved — QMD, Engram, and an agent's own recall are all read-only consumers that leave no trail on the file they read — so there is no citation graph to check a learning against. `origin_session` age is the deterministic, honest proxy for "unreferenced": a learning nobody has reinforced (no newer learning, no operator action) by the time the horizon closes is the candidate. This is a narrower claim than "unused" in the general sense; it is the claim the current store can actually support without new instrumentation.

Dry-run by default: lists candidates with age and title. `--apply` rewrites `status`, `deprecated_by` (`lh memory decay`), `deprecated_on` (today), and `deprecated_reason` (`no reference within N days`) in place, using the same four frontmatter fields `compound_loop.py` already writes as `null`. Every other line — including the exact JSON-flow-style `tags` list — is left byte-identical. The file is never deleted, never moved, and never re-considered once its `status` leaves `active`, so running decay repeatedly is safe.

`learnings/` is one global tree under the knowledge store, not per-project, so `decay` has no `--memory-dir`-style project scoping — only `--learnings-dir` to point at an alternate tree (used by tests).

### `lh memory reconcile`

Two detections, reported separately, over one or every project's `decisions.jsonl`:

1. **Schema drift** (deterministic, always runs). Groups a `decisions.jsonl`'s JSON lines by field set; the most common set is reported as current, every other set as drift, with line numbers. No line is rewritten — the store has no correct value to backfill a `context` that a 2026-04 line never recorded, and inventing one is the guessing this ADR exists to avoid.
2. **Contradiction detection** (semantic, opt-in via `--check-contradictions`). Sends the tail of one project's decisions to the `distill` role and asks it to name contradicting pairs by quoting both summaries verbatim, never to say which is current. Off by default: schema drift is free and store-wide by default, but a bare invocation with no `--memory-dir` fans out over every project in the store, and an LLM pass over all of them is a cost the caller should choose, not trigger by omission.

`reconcile` has no `--apply` at all — not "propose-only for detection 2", propose-only for the whole command. Detection 1 has nothing correct to write; detection 2 is explicit that a human, not the command, picks the surviving fact. This mirrors `consolidate`, which also never writes `MEMORY.md` itself.

## Alternatives considered

- **Track learning retrieval to get a true "unreferenced" signal for decay.** Rejected for this ADR. QMD, Engram and Graphify are three independent read paths and none logs which document it served; instrumenting all three to produce a citation graph is a much larger change than the two commands here, and the age-based proxy already gives the kill-criterion measurement (`--apply` marking fewer than 5% of learnings) a number to act on. A future ADR can add retrieval logging and switch the proxy if age proves too blunt.
- **Give `decay` a semantic-similarity pass instead of an age cutoff**, so a learning reinforced by a near-duplicate recent one is not marked. Rejected for the same reason as above: no consumer records "this old learning is still what I meant" today, so there is no positive signal to check against — only the negative (nothing pointed at it, dated by age).
- **Auto-normalize `decisions.jsonl` schema drift into the current shape.** Rejected. The old lines' missing fields (`context`, `project`, `tags`) were never recorded; filling them with empty strings would look like the compound loop chose to leave them blank, when in fact the schema didn't exist yet. Reporting the drift and leaving the append-only file untouched is honest; rewriting history to look consistent is not.
- **Give `reconcile`'s contradiction detection an `--apply` that appends a "superseded-by" marker to the older decision.** Considered, matching decay's shape. Rejected: `decisions.jsonl` has no schema slot for this (unlike learnings' pre-existing `deprecated_*` fields), and deciding which of two contradicting decisions is "older wins" is exactly the silent-guess failure mode the source article calls out. A future ADR can add the marker field once a human-reviewed acceptance flow (like `proposals accept`) exists for it.
- **Default `reconcile`'s contradiction pass to run automatically alongside schema drift.** Rejected. Schema drift is a free, deterministic scan; the contradiction pass is a paid LLM call per project and the store already has 22 of them. Opt-in via `--check-contradictions` keeps the default invocation free, matching the "reconcile ships schema drift first, contradiction detection is propose-only from the start" sequencing in the design.
- **One `lh memory reconcile-decay` command doing both stages.** Rejected. The two stages answer different questions (Decay: is this still worth carrying forward; Reconcile: do two facts disagree) and have different write contracts (Decay gets `--apply`, Reconcile never does). Splitting them keeps each command's help text honest about what it can and cannot do.

## Consequences

**Positive**
- `learnings/` gains a first mechanism, however conservative, for shrinking below "everything ever captured, forever". The kill criterion (fewer than 5% marked on the first `--apply` run means the horizon is too generous) gives a concrete next step rather than a permanent guess.
- `decisions.jsonl` schema drift — previously invisible to every reader that assumes the current field set — is now a one-command report, store-wide.
- Both commands extend the `consolidate` contract instead of inventing a new one: read-only by default, human-in-the-loop for anything that changes meaning.

**Negative**
- The age-based decay proxy will mark some learnings that are still true and still useful but happen to be old and unreinforced by anything the store can see — the same risk `consolidate`'s human review exists to catch on the `MEMORY.md` side, here caught by `--apply` being opt-in and the mark being `superseded`, never deleted.
- `reconcile --check-contradictions` run without `--memory-dir` against the full store is 22 LLM calls today and grows with every new project; the flag exists so that cost is a deliberate choice, not a silent default.
- Schema drift detection reports a problem it cannot fix; a human (or a later ADR) still has to decide whether to backfill, ignore, or archive the drifted lines.

## Implementation

`src/lazy_harness/core/decay.py`, `src/lazy_harness/core/reconcile.py`, and the `lh memory decay` / `lh memory reconcile` commands in `src/lazy_harness/cli/memory_cmd.py`. Tests mirror both modules under `tests/unit/core/` and the CLI surface under `tests/unit/cli/test_memory_decay.py` and `tests/unit/cli/test_memory_reconcile.py`. See [`specs/designs/2026-09-10-harness-improvements-design.md`](../designs/2026-09-10-harness-improvements-design.md), Track 3.
