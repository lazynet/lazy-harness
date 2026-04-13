# ADR-010: Pre-compact hook preserves working context before compaction

**Status:** accepted
**Date:** 2026-04-13

## Context

Claude Code compacts conversation history when it approaches the context window limit. Compaction is lossy by design — old messages are replaced with a summary. The default summary is a generic LLM digest of the dropped messages, which tends to preserve topic keywords and lose the structured working state: which files were touched, which user intents were still open, which concrete task was in flight.

For a long pair-programming session this matters. The user rarely cares about the phrasing of messages from an hour ago, but almost always cares about "we were in the middle of refactoring X" and "the last thing you edited was Y/Z.py". Losing that is the moment the session feels amnesic.

Claude Code offers a `PreCompact` hook event that fires immediately before compaction, receiving the transcript path on stdin. This is the only window where the raw conversation still exists.

## Decision

Built-in hook at `src/lazy_harness/hooks/builtins/pre_compact.py` that runs on every `PreCompact` event. Responsibilities:

1. **Back up the raw transcript.** Copy the full JSONL to `~/.claude/compact-backups/<timestamp>-<project>.jsonl`. This is a pure forensic artefact — if compaction destroys something we wanted, the raw history is still on disk.
2. **Extract a structured summary.** `parse_transcript` walks the JSONL and collects:
   - The last up-to-5 non-trivial user messages (≥15 chars, truncated to 200). These are the recent intents.
   - Every file path that appears in an assistant `tool_use` block's `input.file_path` or `input.path`. Sorted, deduplicated, last 10 kept. These are the files the session has been working on.
3. **Write the summary to `memory/pre-compact-summary.md`** inside the project's memory directory (`<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/memory/pre-compact-summary.md`). The file starts with an HTML comment recording the generation timestamp.
4. **Return the summary as `hookSpecificOutput.additionalContext`** so Claude Code can optionally include it in the post-compaction context that the model sees.
5. **Always exit 0.** Any failure is logged and swallowed — pre-compact must never prevent compaction itself.

The `context-inject` hook (see [ADR-006](006-hooks-subprocess-json.md) and the memory-model doc) reads `pre-compact-summary.md` on the next session start via `handoff_context`, so the information survives not only the compaction but also the session boundary.

## Alternatives considered

- **Trust Claude Code's default compaction and do nothing.** Loses the working state reliably, observed on real sessions. Rejected.
- **Back up the transcript but generate no summary.** Gives us forensics but no in-model rescue. The backup is still valuable (we keep it), but the summary is what rescues continuity.
- **Call the LLM in the pre-compact hook to produce a summary.** Runs inside Claude Code's compaction window, which is not a safe place to block on another LLM call. Rejected for the same reason compound-loop runs async ([ADR-008](008-compound-loop-async-worker.md)).
- **Parse the transcript into a rich structured object (AST, tool-use graph) rather than "last N user messages + touched files".** Overengineered. The two heuristics above recover 90% of the continuity value and are measurable directly from the JSONL with no semantic analysis.
- **Write the summary into the project's `MEMORY.md` instead of its own file.** Would pollute `MEMORY.md` with rolling session state that is not long-term memory. Kept separate, so `MEMORY.md` stays a stable index and `pre-compact-summary.md` is the ephemeral layer.

## Consequences

- Continuity is measurably better. The next session's `## Handoff from last session` block often includes the pre-compact summary verbatim, giving the model the same file list and tasks without requiring the user to re-explain.
- `~/.claude/compact-backups/` accumulates JSONL files over time. There is no automatic retention policy yet — it will be handled by a scheduler job in a future phase (tracked in `docs/backlog.md`). Manual cleanup is fine in the meantime since JSONL compresses extremely well.
- The hook intentionally consumes input from multiple possible field names (`transcript_path`, `transcriptPath`, `input`) to survive Claude Code schema drift between versions.
- Because the summary lives in the project's memory dir under the deployed profile (`<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/memory/`), it is scoped per-profile and per-cwd — a pre-compact from `work` profile in `/repos/flex/foo` does not contaminate the `personal` profile.
- The combination of pre-compact backup and compound-loop extraction is the reason the framework can recover from catastrophic compaction: even if the in-session summary misses something, the full JSONL is still on disk in `compact-backups/` and the compound-loop worker can be re-run on it.
