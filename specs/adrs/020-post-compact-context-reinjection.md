# ADR-020: Post-compact hook re-injects the pre-compact summary into the live session

**Status:** accepted
**Date:** 2026-04-22

## Context

Claude Code v2.1.117 introduced a `PostCompact` hook event that fires immediately after a conversation is compacted. ADR-010 already covers the `PreCompact` side: `pre_compact.py` backs up the raw transcript, extracts a structured summary of recent user intents and touched files, writes that summary to `pre-compact-summary.md`, and emits it as `hookSpecificOutput.additionalContext` from the PreCompact event.

Whether Claude Code injects the PreCompact event's `additionalContext` into the post-compaction context window is implementation-defined and not guaranteed across versions. If it is silently dropped, the user's working state vanishes from the live session and only resurfaces on the next `SessionStart` (via `context_inject.py`'s `handoff_context`). Continuity within the same session is the gap.

## Decision

Add a built-in hook `post-compact` at `src/lazy_harness/hooks/builtins/post_compact.py` that runs on every `PostCompact` event. Responsibilities:

1. **Read `pre-compact-summary.md`** from `<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/memory/`. This is the file `pre_compact.py` writes; no duplicate parsing of the transcript.
2. **Validate freshness.** If the file's `mtime` is older than `_FRESHNESS_WINDOW_SECONDS = 300` (five minutes) at the moment PostCompact fires, the file belongs to a previous compact, not this one. Skip silently and log `action=skipped reason=stale`.
3. **Emit the body as `hookSpecificOutput.additionalContext`** with `hookEventName: "PostCompact"`. HTML comments are stripped so the model sees clean Markdown.
4. **Always exit 0.** Missing file, unreadable file, empty body — every failure mode logs and exits 0. The hook must never block compaction recovery.

The five-minute window matches `context_inject.py`'s `_STALENESS_WINDOW_SECONDS` (ADR-019) and is justified by the fact that PreCompact and PostCompact run within seconds of each other under normal operation. Any larger gap means the file is stale.

## Alternatives considered

- **Trust PreCompact's `additionalContext` and add no PostCompact hook.** This is what we had. The risk of silent loss was the motivation for this ADR.
- **Re-parse the transcript inside `post_compact.py`.** Duplicates `pre_compact.py` logic and adds CPU cost on every compact for no continuity gain over reading the file. Rejected.
- **Refactor pre/post compact into a shared `_compact_common.py` module.** Premature abstraction for two consumers. Rejected per the repo's "three similar lines beat a premature abstraction" rule.
- **Skip the freshness check.** Would silently re-inject stale context from a previous compact when `pre_compact.py` fails in the current cycle. The check is five lines and prevents a real failure mode.
- **Make the freshness window configurable through `cfg.context_inject` from day one.** YAGNI. The constant matches the `_STALENESS_WINDOW_SECONDS` precedent in `context_inject.py` and can be promoted to config later without changing the hook's external contract.

## Consequences

- Compact-time continuity within the same session no longer depends on Claude Code honouring `additionalContext` from the PreCompact event. The PostCompact event provides a contractually distinct injection point.
- `pre-compact-summary.md` now has three readers: `pre_compact.py` (writer), `post_compact.py` (this ADR), `context_inject.py` (SessionStart). It remains the single source of truth for working-state context across compaction and session boundaries.
- A pre-compact failure that leaves no fresh `pre-compact-summary.md` causes both `additionalContext` paths (PreCompact and PostCompact) to be silently empty. This is detectable via `lh status hooks` (which parses `hooks.log`) — the user will see `pre-compact: never` or stale, and `post-compact: skipped reason=missing`.
- No new dependencies, no new sinks, no new configuration knobs. The hook is ~50 lines of stdlib Python with a single responsibility.
