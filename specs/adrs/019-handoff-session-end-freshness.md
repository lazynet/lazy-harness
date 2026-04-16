# ADR-019: Force a final compound-loop evaluation at session end

**Status:** accepted
**Date:** 2026-04-16

## Context

[ADR-008](008-compound-loop-async-worker.md) deferred compound-loop work out of the `Stop` hook and onto a file-queue worker, and introduced two cost gates to keep the worker cheap on long sessions:

- **Debounce** (`debounce_seconds`, default 60): a task queued within this window suppresses the next Stop event.
- **Growth gate** (`reprocess_min_growth_seconds`, default 300 before this ADR): a new Stop event only re-queues if the session JSONL has grown past this threshold since the last `done/` task.

That was the right call for Stop, which fires after **every LLM turn**. It is the wrong call for the *last* minutes of a session.

Session-close observed in production:

```
13:46:17  Stop #1 → task queued, worker writes handoff.md
13:48:14  Stop #2 → skipped: "no new activity since last process"
13:48:58  Stop #3 → skipped
13:49:21  Stop #4 → skipped
13:49:28  /exit  ← last work done after 13:46:17 never re-evaluated
13:49:31  new session starts, reads stale handoff
```

The handoff the next session saw was a snapshot taken three minutes before `/exit`. The gates were doing exactly what they were designed to do; the information they were gating was the wrong information.

Compounding the failure, the staleness check in `context_inject` marks a handoff stale only when `session_mtime - source_mtime > 300s`. With both thresholds sitting at 300 seconds, the last ~5 minutes of a session falls into a dead zone where the handoff is neither re-evaluated nor flagged.

## Decision

Three coordinated changes. All ship together; each is necessary, none is sufficient alone.

### 1. Lower `reprocess_min_growth_seconds` from 300 → 120

Cuts the worst-case dead-zone at session close from ~5 minutes to ~2. The trade-off is at most ~2× more worker invocations on a long active session — bounded by `debounce_seconds=60` as the floor, and by the worker's single-instance `flock` on collisions. The compound-loop model used for evaluation (`claude-haiku-4-5-20251001` by default) is cheap enough that this is a favourable trade.

### 2. New built-in hook `session-end` wired to Claude Code's `SessionEnd` event

`SessionEnd` fires at true session termination (`/exit`, `/clear`, logout, `prompt_input_exit`). It is observational — purely a cleanup / archival signal — and fires exactly once. Both properties make it the right place to force a final evaluation:

- `session_end.py` replicates the `compound-loop` producer but calls `should_queue_task(..., force=True)` instead of the two separate gates. No debounce, no growth check.
- The helper `should_queue_task(force=bool)` lives in `lazy_harness.knowledge.compound_loop` and is the single intersection point between the two producers. `force=True` is the caller's assertion that "the session is closing; the handoff must reflect its final state."
- The hook must still exit 0 under every failure mode. `SessionEnd` cannot block shutdown, and the shutdown path is not a useful place for error reporting.

### 3. New CLI command `lh knowledge handoff-now`

Same semantics as `session-end`, but driven by the user. Motivations:

- **Harness-agnostic fallback.** If the user switches off Claude Code, or their CC build predates `SessionEnd`, the force path still works.
- **Explicit intent.** "I just resolved the pending items, capture that *now*, before I keep working." Useful before `/compact` too — a stale handoff also harms the pre-compact pipeline.
- **Slash command target.** Users can wire a custom slash command (e.g. `/wrap`) to this subcommand without `lazy-harness` having to define slash commands itself.

## Alternatives considered

- **Lower `reprocess_min_growth_seconds` only.** Reduces the dead zone but does not eliminate it: a user who resolves the last pending item *N* seconds before `/exit`, with *N* below the threshold, is still unlucky. The threshold is a cost control, not a correctness bound.
- **Harden the staleness check in `context_inject` and do nothing else.** Informs the next session that the handoff may be stale, but does not preserve the work that was lost. Defensive, not curative.
- **Extract the whole producer into a shared module and call it from both hooks.** Cleaner than the current mild duplication between `compound_loop.py` and `session_end.py`. Deferred: the two producers differ in log prefix and gate semantics, and consolidating them would require introducing a parameterisation (`prefix`, `force`) that hides the important difference behind keyword arguments. Re-evaluate if a third producer appears.
- **Wait for Claude Code to emit a richer event (e.g. pre-`/exit`).** No such event exists and `SessionEnd` is the intended hook point for shutdown-time work. Waiting would indefinitely defer the fix.
- **Rely solely on `lh knowledge handoff-now`.** Puts the burden on the user to remember. Most sessions do not end with a ceremonial close; people type `/exit` or close the terminal. The hook has to be the default path.

## Consequences

- `SessionEnd` is now a supported hook event in the Claude Code adapter (`supported_hooks()` and `generate_hook_config` both map `session_end` → `SessionEnd`). Deployments that opt in wire `lh hook session-end` into their `settings.json`.
- `should_queue_task(force=bool)` is the one place where the force-vs-gate decision is made. Future producers (e.g. a `PreCompact`-driven forced run) can call the same helper with `force=True`.
- The existing `compound-loop` hook is unchanged. It keeps its gates, its log prefix, and its tests. The duplication between it and `session-end` is deliberate and documented.
- `handoff.md` provenance is unaffected: the frontmatter still records `session_id`, `written_at`, and `source_mtime`, and the staleness classifier in `context_inject` remains the belt-and-suspenders check. With the new force path the classifier should hit "stale" much less often in practice.
- Users on older Claude Code builds (no `SessionEnd`) get the config-level improvement for free (lower growth threshold) and can opt into `lh knowledge handoff-now` as a manual wrap command.
- The worker cost goes up modestly. Per hour of active session: at most one extra evaluation from the lower threshold plus one extra evaluation on close. The single-instance `flock` prevents cascades.
