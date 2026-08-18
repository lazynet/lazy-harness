# ADR-036: Compact-event hooks use the channels the agent actually provides

**Status:** accepted
**Date:** 2026-08-18
**Supersedes:** ADR-020
**Superseded by:** —
**Related:** ADR-006 (hooks as subprocess JSON), ADR-010 (pre-compact preservation)

## Context

ADR-010 has `pre_compact.py` emit its summary as
`hookSpecificOutput.additionalContext` on the `PreCompact` event. ADR-020 adds
`post_compact.py` doing the same on `PostCompact`, and justifies itself with
this sentence:

> a path Claude Code is contractually obliged to honour
> (`hookSpecificOutput.additionalContext` on the PostCompact event itself)

There is no such contract. Both hooks have been failing schema validation on
every compaction, printing an error to the user and injecting nothing:

```
PreCompact [.../pre_compact.py] failed: Hook JSON output validation failed — (root): Invalid input
PostCompact [.../post_compact.py] failed: Hook JSON output validation failed — (root): Invalid input
```

Read out of the Claude Code 2.1.234 bundle rather than out of its
documentation, the `hookSpecificOutput` union carries variants for
`CwdChanged`, `Elicitation`, `ElicitationResult`, `FileChanged`,
`MessageDisplay`, `Notification`, `PermissionDenied`, `PermissionRequest`,
`PostToolBatch`, `PostToolUse`, `PostToolUseFailure`, `PreToolUse`,
`SessionStart`, `Setup`, `Stop`, `SubagentStart`, `SubagentStop`,
`UserPromptExpansion`, `UserPromptSubmit` and `WorktreeCreate`. `PreCompact`
and `PostCompact` are valid *events* with no output variant at all.

The two executors differ in what they do with a hook's result:

- **`PreCompact`** collects the raw stdout of every hook that succeeded and
  was not blocked, and returns the joined text as `newCustomInstructions` —
  which steers the compaction summariser. Plain text reaches the model. JSON
  that fails validation marks the hook failed, so its output is dropped.
- **`PostCompact`** returns `{userDisplayMessage}` and nothing else. Its
  output reaches the terminal and never the model.

So the gap ADR-020 set out to close — continuity *within* the same session —
cannot be closed from that event. The error was not a bad implementation of a
sound design; the design assumed a channel that does not exist.

Note also that the "Expected schema" block Claude Code prints alongside the
validation error is abbreviated, not exhaustive: it omits `SessionStart`,
which demonstrably works. Reading it as the union leads to the wrong repair.

## Decision

1. **Remove the `post-compact` built-in.** Delete the module, its
   registration in `_BUILTIN_HOOKS`, and its entry in `_DEFAULT_ON_HOOKS`. The
   `post_compact` → `PostCompact` mapping stays in the Claude Code adapter:
   the event is real and an operator may still attach their own hook to it.
2. **`pre-compact` prints plain text.** The summary goes to stdout preceded by
   `SUMMARY_PREAMBLE` — "Preserve the following working context in the
   summary:". `newCustomInstructions` is a directive channel, so an unframed
   dump of decisions and file paths reads as a wall of unexplained assertions
   to the summariser.
3. **Post-compaction continuity stays with `context-inject`.** It already
   reads `pre-compact-summary.md` on `SessionStart` with source `compact`,
   through a variant that exists. That path is verified working; it is what
   delivered the summary during the compaction that surfaced this ADR.

## Consequences

- `pre-compact-summary.md` keeps its role as the single source of truth. One
  writer (`pre-compact`), one reader (`context-inject`).
- A profile deployed before this change carries a `PostCompact` entry in
  `settings.json` pointing at a module that no longer exists. `lh deploy`
  removes it, because the harness owns the entries it generated.
- The framework no longer claims post-compact re-injection anywhere in
  `docs/`. It never did it.
- If a future Claude Code adds a `PostCompact` output variant, this decision
  is cheap to revisit — but the burden of proof is a read of the bundle, not
  a line in the changelog.

## Verification

`grep -ao 'hookEventName:[a-zA-Z"(). |]\{0,120\}' <claude-binary> | sort -u`
enumerates the union. `grep -abo 'function <executor>('` plus a `dd` at that
offset shows what each event does with a hook's result. Both were run against
`~/.local/share/claude/versions/2.1.234` before this ADR was written.
