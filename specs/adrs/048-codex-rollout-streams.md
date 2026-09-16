# ADR-048: Codex's rollout is two streams — which one each signal is read from

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-041 (multi-agent hook contract), ADR-044 (Codex's native edit path), ADR-046 (a delete is not an edit)

## Context

Step 12 of `specs/designs/2026-09-13-multi-agent-harness-design.md` (`:1895-1905`)
asks for a `TranscriptReader` on `CodexAdapter`, against a rollout format
"now observed rather than assumed". Decision 11 (`:1127-1178`) supplies the
contract: a reader declares the `Signal`s it delivers, and a hook deploys only
where every signal it needs is available.

The format was measured before anything was written —
`specs/designs/codex-evidence.md` §5, 15 rollout files, 1.147 lines, all from
`codex-cli 0.154.0`. Three questions came out of that measurement that the
design does not answer, because it could not have known to ask them.

**One refusal is not among them.** `GOAL_STATUS` is not declared because no kind
and no payload field in any of the 15 sessions marks an explicit goal; that
follows from decision 11 and the measurement, and needs no decision here.

### The three the measurement raised

**A rollout is two interleaved streams, and the same fact is in both.** The
model's own items arrive as `response_item/*` and `token_usage_record`; the TUI's
view of the same turn arrives as `event_msg/*`. A turn is a
`response_item/message` *and* an `event_msg/item_completed` carrying an
`AgentMessage` item. A turn's accounting is a `token_usage_record` *and* an
`event_msg/token_count`. Reading both doubles every count a consumer takes.

**The `exec` tool's argument is not a command.** 154 of 154 `custom_tool_call`
entries are named `exec`, and their `input` is a bare string that is not JSON:
all 154 multiline, all containing `await `, first tokens `text`/`const`/`for`/
`await`. It is a program for Codex's cell runtime (`unified_exec`), and the
`function_call` named `wait` with `{cell_id, yield_time_ms}` is the other end of
it. The shell command that program eventually runs appears only in the *other*
stream, as `item_completed/CommandExecution.command` — always
`["/bin/zsh", "-lc", "<script>"]`, with no `call_id` pairing it to the call.

**The file name's timestamp is not a modification time.** `locate_sessions` is
given `since`, which `agents/base.py` defines as filtering "by last
modification". Codex names a rollout
`rollout-<YYYY-MM-DD>T<HH-MM-SS>-<uuid>.jsonl`, and that stamp is the session's
*start* in **local wall-clock with no offset**: a file named `...T09-02-04-...`
whose first record is `2026-09-16T12:02:13.926Z`, three hours apart on a UTC-3
host.

## Decision

**D1 — one stream per signal, and the `event_msg` stream is not it.** `MESSAGES`
and `TOOL_CALLS` are read from `response_item`, `TOKEN_USAGE` from
`token_usage_record`. Every `event_msg` kind is skipped. The model's stream wins
because it is the record of what happened rather than of what was drawn, and
because `call_id` lives there — `TranscriptEvent.tool_use_id` exists to pair a
call with its result, and the `event_msg` items carry no id at all.

`MESSAGES` is further restricted to the roles `user` and `assistant`. The third
role in the stream, `developer` (46 of 151 messages), is Codex's instruction
channel — the composed `AGENTS.md` and config text, re-sent every turn.
`knowledge/session_export.py:56` labels every non-`user` role as the model
speaking, so emitting it would write a profile's own instructions into the
exported conversation as though the model had said them.

**D2 — the `exec` program is `raw_input`, never `command`.** The reader hands
`_parse_tool` a `{"input": <program>}` mapping, which that method does not read,
so `ToolCall.command` stays `None` and `operation` stays `None`.
`pre_tool_use_security.py:362` and `pre_tool_use_git_scope.py:402` both scan
`tool.command` as shell text; a TypeScript program there would put the model's
source in front of a command denylist and match on lines nothing is executing.
This is the same refusal `_parse_tool` already makes for a patch blob, for the
same reason.

The consequence is stated rather than hidden: a `TOOL_CALLS` event from a Codex
rollout names the tool and its id, and carries no command and no path. Nothing
consumes `TOOL_CALLS` today — no builtin declares it — so this costs no hook.

**D3 — `since` filters on mtime; the file name is not parsed.** The reader globs
`sessions/**/rollout-*.jsonl` and compares `st_mtime`, exactly as the Claude Code
reader does. The name's stamp is refused on two counts: it answers the wrong
question (start, not modification — a session open for four hours is excluded by
its own start time), and it is unreadable without the offset of the machine that
wrote it, which the name does not carry.

## Consequences

- A consumer counting Codex turns or summing Codex tokens gets each one once.
  The cost is that the richer `event_msg` fields — `exit_code`, `cwd`,
  `duration`, `parsed_cmd` — are not reachable through this reader. They are one
  decision away if a consumer ever needs them, and that decision is this one,
  revisited with a name for what a `CommandExecution` event would be.
- File edits are not visible. In 0.154.0's cell-runtime mode no rollout entry is
  a `custom_tool_call` named `apply_patch` (0 of 154), and the only line naming
  the touched paths is `item_completed/FileChange`, which D1 drops. A rollout
  that does carry an `apply_patch` call is a one-line mapping and a test —
  recorded in `codex-evidence.md` §5.5 so it is found rather than rediscovered.
- `GOAL_STATUS` stays a gap on every Codex profile. `lh doctor` now reports it as
  *"codex's TranscriptReader does not deliver it"* instead of *"codex has no
  TranscriptReader"* — the `HookSignalGap.has_reader` distinction, which is the
  difference between extending a reader and writing one.
- The reader is pinned to `0.154.0` in its docstring and in the evidence table,
  and there is no version switch. A second version has never been observed, and
  a branch nothing has exercised is the guess this adapter exists to avoid. The
  first rollout that does not parse under these rules is what reopens this.
- D3 leaves the day-directory layout unused. `sessions/<YYYY>/<MM>/<DD>/` would
  let a `since` scan skip whole directories without a `stat`, and the margin
  needed to make that timezone-safe is a day. Not taken: the walk is already
  lazy, and no measurement shows the `stat` costing anything.
