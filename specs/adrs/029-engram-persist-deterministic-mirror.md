# ADR-029: Deterministic Engram mirror via Stop hook

**Status:** accepted
**Date:** 2026-05-04
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-006 (hooks-subprocess-json), ADR-008 (compound-loop-insight-capture), ADR-027 (memory-stack-overview)

## Context

The five-layer memory model (ADR-027) names Engram as the episodic-raw layer and documents a Stop-time persistence path for it. Until this ADR, no hook in the harness invoked Engram: the documented behaviour was inoperative. An audit on 2026-05-04 confirmed the gap (10 of 11 Engram projects had a single bootstrap observation and zero sessions).

## Decision

Add a built-in `engram-persist` hook to the `Stop` chain, after `compound_loop.py`. On every Stop event, the hook reads new entries from `decisions.jsonl` and `failures.jsonl` since the last persisted byte cursor and mirrors each entry into Engram via `engram save` (CLI subprocess, not the MCP server). The cursor advances only on successful save, giving at-least-once semantics with no duplicate emission under normal operation.

The hook forces `--project <basename>` derived from `git rev-parse --path-format=absolute --git-common-dir` (the basename of its parent, so a worktree resolves to its main repository) to prevent the project-key fragmentation observed in the audit (`lazy-harness` vs `lazynet/lazy-harness`). It is fail-soft: missing binary is a no-op with one warning, save failures keep the cursor unchanged for retry on the next Stop.

## Consequences

**Positive**
- Engram becomes a deterministic episodic store fed by every Stop, matching the doc.
- Existing JSONL artifacts remain the human-reviewable source of truth; Engram is a 1:1 mirror with full search.
- Cursor + at-least-once semantics make the hook safe to retry, including across restarts.

**Negative**
- Stop chain runs an extra subprocess per Stop. With 1–3 entries per Stop at 50–200ms each, expect 50–600ms added latency. Slow-save events flag regressions above a 500ms threshold.
- Backfill on first run mirrors every entry currently in JSONL (one-time cost).
- Existing fragmented Engram projects need a one-time `engram projects consolidate --all` before opt-in.

## Alternatives considered

1. **Per-session summary at SessionEnd**: lower volume but loses granular searchability; needs new aggregation logic. Rejected — does not match the JSONL artifacts.
2. **MCP-based persistence (`mem_save` tool from the agent)**: requires the agent to remember to call it; observed empirically to be unreliable. Rejected — defeats the determinism goal.
3. **Extending `compound_loop.py` to also push to Engram**: mixes two concerns (insight evaluation and storage mirror) into one module. Rejected — separate hook keeps responsibilities clean and tests focused.

## Implementation

See `specs/designs/2026-05-04-engram-persist-hook-design.md` and `specs/plans/2026-05-04-engram-persist-hook-plan.md`.

## Evolution — 2026-09-24: one cursor per project per machine, and a bounded run

The cursor first lived beside the JSONL in the memory dir. Once memory moved
into the knowledge store, that copy travelled between machines with the store
while the Engram database it indexes did not, so it moved to the agent runtime
dir, `<agent dir>/engram-cursors/<host>/<owner>/<name>/engram_cursor.json`.
That made it per *profile*: every profile on a machine appends to the same
`decisions.jsonl` and saves into the same `~/.engram/engram.db`, yet each kept
its own offsets. A profile's first run re-uploaded everything the others had
already mirrored — 405 entries (63 s) in one profile and 930 (145 s, `Stop`
blocked throughout) in another — and a machine's database was measured holding
7,116 decision/failure rows for 2,048 JSONL lines. Engram collapses an
identical save only inside a short window (the closest separate duplicate
rows were ~15 minutes apart), so it does not absorb a re-upload.

- **Location.** When memory lives in the store, the cursor is
  `<lh data dir>/engram-cursors/<memory dir relative to the store root>/engram_cursor.json`:
  keyed by the memory it indexes, shared by every profile, never synced. Memory
  outside the store is itself per profile, so its cursor stays in
  `<agent dir>/engram-cursors/...`.
- **Carry-over.** The first run with no shared cursor adopts, per file, the
  furthest offset any profile's old cursor reached — each of them fed the same
  database. The store's own copy is read only when no profile cursor exists.
- **Cap.** A run attempts at most `MAX_SAVES_PER_RUN` (25) saves across both
  files; the cursor advances only over what was saved, and the rest drains on
  later `Stop` events. The existing duplicate rows are left in place.

`lh doctor` reports lag of at least 64 KiB as `warn` with `catching up` only
when the latest run reached the cap, the cursor file advanced on disk, and no
save failed in that run. A stalled cursor remains `fail` even if `engram save`
returned success.
