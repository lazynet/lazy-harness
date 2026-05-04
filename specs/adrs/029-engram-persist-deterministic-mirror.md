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

The hook forces `--project <basename>` derived from `git rev-parse --show-toplevel` to prevent the project-key fragmentation observed in the audit (`lazy-harness` vs `lazynet/lazy-harness`). It is fail-soft: missing binary is a no-op with one warning, save failures keep the cursor unchanged for retry on the next Stop.

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
