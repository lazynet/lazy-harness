# PostCompact built-in hook — design

**Date:** 2026-04-22
**Status:** approved (pending implementation)
**Related:** ADR-006 (hooks-subprocess-json), ADR-010 (pre-compact-preservation), ADR-019 (handoff-session-end-freshness)

## Context

Claude Code v2.1.117 added a `PostCompact` hook event that fires immediately **after** the conversation is compacted. The existing `pre_compact.py` built-in (ADR-010) runs **before** compaction, backs up the raw transcript, and writes a structured summary to `pre-compact-summary.md`. It also returns the summary as `hookSpecificOutput.additionalContext` from the PreCompact event, but whether Claude Code injects that text into the post-compact context window is implementation-defined and not guaranteed across versions.

The risk is silent loss: if PreCompact's `additionalContext` is dropped, the user's working state — recent intents, files in flight — vanishes from the live session and only resurfaces on the next `SessionStart` (via `context_inject.py` which already reads `pre-compact-summary.md`). Continuity within the same session is the gap.

## Decision

Add a built-in hook `post-compact` that runs on every `PostCompact` event. Its sole job is to **re-emit** the summary already produced by `pre_compact.py` so that the post-compaction context window receives it through a path Claude Code is contractually obliged to honour (`hookSpecificOutput.additionalContext` on the PostCompact event itself).

The hook is deliberately a thin re-emitter. It does not parse the transcript, generate new text, or call any external service. It reads the file `pre_compact.py` already wrote; if that file is missing or stale, it skips silently.

### Single source of truth

`pre-compact-summary.md` (under `<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/memory/`) remains the single source of truth for compact-related working-state context. Three consumers now share it:

| Consumer            | Event         | When it reads                                          |
|---------------------|---------------|--------------------------------------------------------|
| `pre_compact.py`    | PreCompact    | Writes the file. Also emits as `additionalContext`.    |
| `post_compact.py`   | PostCompact   | Re-emits as `additionalContext` (this design).         |
| `context_inject.py` | SessionStart  | Reads as part of `## Handoff from last session`.       |

### Freshness check

To prevent re-injecting context from a previous compact (e.g. when `pre_compact.py` failed silently in this cycle but the file from an earlier cycle still exists), the hook checks `pre-compact-summary.md`'s `mtime`. If the file is older than `_FRESHNESS_WINDOW_SECONDS = 300` (5 minutes) at the moment PostCompact fires, the hook skips and logs `action=skipped reason=stale`.

The 5-minute window is the same order of magnitude as `context_inject.py`'s `_STALENESS_WINDOW_SECONDS = 300` and is justified by the fact that PreCompact and PostCompact run within seconds of each other under normal operation. Any larger gap means the file is from a previous compact, not this one.

## Components

1. **`src/lazy_harness/hooks/builtins/post_compact.py`** — new module. Entrypoint, freshness check, JSON output.
2. **`src/lazy_harness/hooks/loader.py`** — register `"post-compact": "lazy_harness.hooks.builtins.post_compact"` in `_BUILTIN_HOOKS`.
3. **`tests/unit/test_builtin_post_compact.py`** — new module, mirrors `test_builtin_pre_compact.py` (subprocess-based).
4. **`specs/adrs/020-post-compact-context-reinjection.md`** — new ADR recording the decision.
5. **`specs/adrs/README.md`** — index entry for ADR-020.

## Data flow

```
PostCompact event (Claude Code)
        │
        ▼
engine.execute_hook(post_compact.py, payload)
        │
        ▼
resolve memory_dir = $CLAUDE_CONFIG_DIR/projects/<encoded-cwd>/memory
        │
        ▼
stat pre-compact-summary.md
        │
        ├── missing      ─▶ log "fired cwd=X action=skipped reason=missing"; exit 0
        │
        ├── mtime stale  ─▶ log "fired cwd=X action=skipped reason=stale";   exit 0
        │
        └── fresh
              │
              ▼
        read body, strip lines starting with "<!--"
              │
              ▼
        stdout: {"hookSpecificOutput":{"hookEventName":"PostCompact","additionalContext":body}}
        log "fired cwd=X action=injected summary_chars=N"; exit 0
```

The hook reads stdin (PostCompact payload) but does not require any field from it. Reading is solely for protocol consistency with the engine.

## Error handling

| Failure mode                           | Behaviour                                            |
|----------------------------------------|------------------------------------------------------|
| `pre-compact-summary.md` does not exist | Log `skipped reason=missing`; exit 0; no stdout.    |
| `mtime` older than freshness window    | Log `skipped reason=stale`; exit 0; no stdout.       |
| `OSError` on `stat` or `read`          | Log the error; exit 0; no stdout.                    |
| `JSONDecodeError` on stdin             | Ignore (the hook does not need any payload field).   |
| Any unexpected exception               | Caught at top level; exit 0; logged.                 |

**Invariant:** the hook must never block compaction recovery. Every failure path exits 0 and produces at most a log line.

## Logging

All log lines go to `<CLAUDE_CONFIG_DIR>/logs/hooks.log`, prefixed `post-compact:`. Format mirrors `pre_compact.py`:

```
2026-04-22T10:00:00-03:00 post-compact: fired cwd=/repos/lazy/lazy-harness action=injected summary_chars=420
2026-04-22T10:01:15-03:00 post-compact: fired cwd=/repos/lazy/lazy-harness action=skipped reason=missing
```

The `cwd=...` and `action=...` fields are parseable by the existing `lh status hooks` view (`src/lazy_harness/monitoring/views/hooks.py`) and by future ad-hoc grep / awk over `hooks.log`. No new sink, no sqlite write from inside the hook (consistent with the rest of the built-ins).

## Testing

Subprocess-based unit tests in `tests/unit/test_builtin_post_compact.py`, mirroring the structure of `test_builtin_pre_compact.py`:

1. **Happy path — fresh summary present.** Pre-create `pre-compact-summary.md` with mtime = now under a fake `CLAUDE_CONFIG_DIR`. Run the hook. Assert exit 0, assert stdout parses to JSON containing `hookSpecificOutput.additionalContext` equal to the file body (with HTML comments stripped), assert `hookEventName == "PostCompact"`.
2. **Missing summary.** No file present. Run the hook. Assert exit 0, assert stdout is empty (no JSON output).
3. **Stale summary.** Pre-create the file but `os.utime` it to an mtime > `_FRESHNESS_WINDOW_SECONDS` ago. Assert exit 0, assert stdout empty.
4. **Empty stdin.** Send `"{}"`. Assert exit 0 (no crash, no required field).

All tests use `tmp_path` and an isolated `CLAUDE_CONFIG_DIR` so they never touch the real `~/.claude`.

## Doc impact

- **ADR-020** (new) — records this decision and points back to ADR-010.
- **`specs/adrs/README.md`** — append index entry for ADR-020.
- **`CLAUDE.md` (root)** — no change. The contract does not enumerate built-in hooks.
- **`docs/`** (public site) — no change in this PR. If a public catalog of built-in hooks is added later, `post-compact` is included there.

## Out of scope

- No retention policy for `compact-backups/` (still tracked separately).
- No metric persistence to sqlite from inside the hook (covered by future work if a concrete query need appears; YAGNI for now).
- No new configurability knobs (`enabled`, `max_chars`, custom freshness window). Hardcoded constant matches the precedent of `_STALENESS_WINDOW_SECONDS` in `context_inject.py`. If the need arises, a follow-up makes it configurable through `cfg.context_inject` without changing this hook's external contract.

## Alternatives considered

- **Re-parse the transcript inside `post_compact.py`** (Approach 2 from brainstorming). Rejected — duplicates `pre_compact.py`'s logic and adds CPU cost on every compact for no continuity gain over reading the file.
- **Refactor pre/post compact into a shared `_compact_common.py`** (Approach 3). Rejected — premature abstraction for two consumers. Three similar lines beat a premature abstraction (repo rule).
- **No freshness check** (Approach 1). Rejected — silently re-injects stale context from a previous compact when `pre_compact.py` fails in the current cycle. The freshness check is five lines and prevents a real failure mode.
- **Make freshness window configurable from day one.** Rejected — YAGNI. Constant matches precedent and can be promoted to config in a follow-up if needed.
