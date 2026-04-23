# How hooks work

This page explains the hook lifecycle end to end: what events exist, what gets triggered when, how built-in hooks behave, where they write, and how you extend the system with your own.

If you want the **why** behind the design choices, see [ADR-006 — Hooks as subprocess with JSON stdin/stdout](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/006-hooks-subprocess-json.md) and [ADR-008 — Compound-loop async worker](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/008-compound-loop-async-worker.md). This page is the how.

## The model

A hook is an executable that:

1. Is invoked by the agent (not by `lazy-harness`) when a specific event fires.
2. Reads a JSON payload describing the event from stdin.
3. Optionally writes a JSON object with `hookSpecificOutput` on stdout.
4. Exits with code 0. **Always.** A hook that exits non-zero risks breaking the agent's session.

Built-in hooks ship inside the framework as Python scripts under `src/lazy_harness/hooks/builtins/`. User hooks live under `~/.config/lazy-harness/hooks/<name>.py` (or whatever language you prefer as long as the binary is executable and reads stdin).

Declaration happens in `config.toml`:

```toml
[hooks.session_start]
scripts = ["context-inject"]

[hooks.session_stop]
scripts = ["session-export", "compound-loop"]

[hooks.session_end]
scripts = ["session-end"]

[hooks.pre_compact]
scripts = ["pre-compact"]

[hooks.post_compact]
scripts = ["post-compact"]
```

`lh deploy` reads this, resolves each name (builtin first, user dir second), and generates the agent's native hook config — `settings.json` for Claude Code. From then on, the agent itself spawns the hooks.

## Event glossary

| `config.toml` event | Claude Code event | When it fires | Typical use |
|---|---|---|---|
| `session_start` | `SessionStart` | Right after Claude Code starts a session | Inject additional context |
| `session_stop` | `Stop` | After every LLM turn (not once at shutdown) | Export session, queue gated async work |
| `session_end` | `SessionEnd` | Exactly once at real session termination (`/exit`, `/clear`, logout) | Force final end-of-session work |
| `pre_compact` | `PreCompact` | Immediately before Claude Code compacts conversation history | Preserve working state |
| `post_compact` | `PostCompact` | Immediately after Claude Code compacts conversation history | Re-inject preserved working state |
| `pre_tool_use` | `PreToolUse` | Before each tool call | Guardrails, policy enforcement |
| `post_tool_use` | `PostToolUse` | After each tool call | Logging, side-effect observers |
| `notification` | `Notification` | Ad-hoc agent notifications | Desktop notifications, integrations |

The mapping lives in `ClaudeCodeAdapter.generate_hook_config` — other agents may expose different event names, but the `config.toml` side is stable.

## The built-ins

### `context-inject` — runs on `SessionStart`

Source: `src/lazy_harness/hooks/builtins/context_inject.py`.

Responsibility: pull together everything a new session should know about, wrap it in markdown sections, and print it as `hookSpecificOutput.additionalContext` so the agent sees it alongside the first user message.

Sections composed, in priority order:

1. **`## Git`** — current branch, last commit, working-tree status (modified / untracked count). Computed with a short-timeout `git` subprocess; absent if the cwd is not inside a git repo.
2. **`## LazyNorth`** — your strategic compass file (universal + per-profile), if `[lazynorth]` is enabled in config. Truncated to ~20 lines for the universal doc and ~15 for the per-profile one.
3. **`## Last session`** — the most recent exported session matching this project's name. Displays date, message count, and the first non-empty user message of that session (truncated to 80 chars). Pulled from the knowledge directory, so it is scoped by project and spans profiles if you run multiple.
4. **`## Handoff from last session`** — contents of `memory/handoff.md` (written by `compound-loop`) plus `memory/pre-compact-summary.md` (written by `pre-compact`) from the project's per-cwd memory dir.
5. **`## Recent history`** — the last 3 entries from `decisions.jsonl` and the last 3 from `failures.jsonl`, with failures including their prevention field.

The body is truncated to `cfg.context_inject.max_body_chars` (default 3000) by dropping sections in the order `episodic → lazynorth → handoff`. A compact banner is also emitted as `systemMessage` so the agent can surface "Session context loaded: on main | Last session: 2026-04-12 18:32 | has handoff notes" without printing the full body.

**Where it writes:** nowhere on disk. It only prints to stdout. Its job is read-only composition.

### `pre-compact` — runs on `PreCompact`

Source: `src/lazy_harness/hooks/builtins/pre_compact.py`.

Responsibility: rescue working state before Claude Code compacts the conversation.

Steps when the event fires:

1. Read the transcript path from the event JSON (accepts `transcript_path`, `transcriptPath`, or `input` field — tolerant to Claude Code version drift).
2. Copy the raw transcript to `~/.claude/compact-backups/<timestamp>-<project>.jsonl`. This is the forensic backup; nothing in the framework relies on it, but `lh` users can re-run compound loop against it if needed.
3. Parse the JSONL and extract:
   - The last up to 5 non-trivial user messages (length ≥ 15 chars, truncated to 200 chars each).
   - Every file path seen inside assistant `tool_use` blocks' `input.file_path` or `input.path`. Sorted, deduplicated, last 10 kept.
4. Build a markdown summary with `## Tasks in progress` and `## Files worked on` sections.
5. Write it to `<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/memory/pre-compact-summary.md` with a generation timestamp in an HTML comment.
6. Also return it as `hookSpecificOutput.additionalContext` so the agent can optionally keep it in the post-compaction window.

**Where it writes:**
- `~/.claude/compact-backups/<ts>-<project>.jsonl` — raw transcript backup.
- `<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/memory/pre-compact-summary.md` — distilled summary for the next session start.

### `post-compact` — runs on `PostCompact`

Source: `src/lazy_harness/hooks/builtins/post_compact.py`.

Responsibility: re-inject the summary `pre-compact` already wrote into the live post-compaction context window of the same session, so working-state continuity does not depend on Claude Code honouring `additionalContext` from the `PreCompact` event.

Steps when the event fires:

1. Resolve the per-project memory dir at `<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/memory/` and stat `pre-compact-summary.md`.
2. If the file does not exist, log `action=skipped reason=missing` and exit 0.
3. If the file's `mtime` is older than 5 minutes (the freshness window), log `action=skipped reason=stale` and exit 0. This prevents re-injecting context from a previous compact when `pre-compact` failed silently in the current cycle.
4. Strip HTML comments from the body and emit it as `hookSpecificOutput.additionalContext` with `hookEventName: "PostCompact"`.

The hook is a thin re-emitter: it does not parse the transcript, generate new text, or call any external service. `pre-compact-summary.md` remains the single source of truth — `pre-compact` writes it, `post-compact` re-emits it for the live session, `context-inject` reads it for the next session.

**Where it writes:** nowhere on disk. It only prints to stdout. Logs go to `<CLAUDE_CONFIG_DIR>/logs/hooks.log` like every other built-in.

See ADR-020 for the full rationale.

### `session-export` — runs on `Stop`

Source: `src/lazy_harness/hooks/builtins/session_export.py`, backed by the pure `export_session` in `src/lazy_harness/knowledge/session_export.py`.

Responsibility: convert the just-ended session's JSONL into a clean markdown file in the knowledge directory, then re-index with QMD if available.

Flow:

1. Locate the latest `*.jsonl` under `<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/`.
2. Parse it into metadata + messages. Sessions without a `permission-mode` first record are treated as non-interactive and skipped.
3. Filter sessions under `min_messages` (default 4) — scratch prompts never make it into the knowledge tree.
4. Classify the session by cwd heuristics (see [ADR-011](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/011-session-export-and-classification.md)) to compute `profile` and `session_type`.
5. Write to `<knowledge.path>/sessions/YYYY-MM/YYYY-MM-DD-<short-id>.md` with frontmatter (`session_id`, `cwd`, `project`, `profile`, `session_type`, `branch`, `claude_version`, `messages`) and a body of `## User` / `## Claude` sections.
6. Atomic write via tempfile + `os.replace` (iCloud / Dropbox safe).
7. If `qmd` is on PATH, run `qmd update` to re-index.

**Where it writes:** `<knowledge.path>/sessions/YYYY-MM/*.md`. Idempotent — re-running on the same session only writes if the new message count exceeds the existing export's.

### `compound-loop` — runs on `Stop`

Source: `src/lazy_harness/hooks/builtins/compound_loop.py` (the producer) + `src/lazy_harness/knowledge/compound_loop_worker.py` (the consumer) + `src/lazy_harness/knowledge/compound_loop.py` (the pure functions).

Responsibility: distill the session into structured decisions, failures, learnings, and handoff items — **asynchronously**, so session close stays instant.

This is the hook that does the heaviest lifting. It is split into two pieces deliberately ([ADR-008](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/008-compound-loop-async-worker.md)):

**Producer (in-hook, fast):**
1. Check `compound_loop.enabled` in config, bail if disabled.
2. Find the latest session JSONL for the current cwd.
3. Apply debounce (`debounce_seconds`, default 60) — if a task for this session was queued within the window, skip.
4. Apply the growth gate (`reprocess_min_growth_seconds`, default 120) — re-queue only if the JSONL grew past the threshold since the last `done/` task.
5. Check `queue/done/` for the same short session id — if already processed, skip.
6. Drop a task file (`<unix-ts>-<short-id>.task`) into `~/.claude/queue/` with key=value metadata (`cwd`, `session_jsonl`, `session_id`, `memory_dir`, `timestamp`).
7. `subprocess.Popen` the worker as a detached process. Return immediately.

**Consumer (worker, slow, async):**
1. Acquire `fcntl.flock` on `~/.claude/queue/.worker.lock`. If another worker is running, exit 0.
2. Drain `*.task` files in FIFO order.
3. For each task: parse metadata → filter trivial sessions (`min_user_chars`, `min_messages`) → collect existing decisions/failures/learnings for deduplication → build prompt with `build_prompt` (ported verbatim from the predecessor; the wording is calibration, not code) → call `claude -p --model <model>` with a configurable timeout → parse the JSON response with `parse_response` (handles bare JSON, fenced JSON, and prose-preamble JSON) → persist with `persist_results`.
4. Move the task to `queue/done/` regardless of outcome — failures never block the queue.

**Where it writes (via `persist_results`):**
- `<memory_dir>/decisions.jsonl` — appended structured decisions.
- `<memory_dir>/failures.jsonl` — appended preventable errors.
- `<learnings_dir>/YYYY-MM/YYYY-MM-DD-<slug>.md` — one markdown file per learning, atomic write.
- `<memory_dir>/handoff.md` — overwritten with the current pending items, or deleted if empty.

`<memory_dir>` is `<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/memory/`. `<learnings_dir>` is resolved from `LCT_LEARNINGS_DIR` if set (back-compat), otherwise `<knowledge.path>/<compound_loop.learnings_subdir>`.

### `session-end` — runs on `SessionEnd`

Source: `src/lazy_harness/hooks/builtins/session_end.py`.

Responsibility: force one final compound-loop evaluation when the session actually closes (`/exit`, `/clear`, logout, `prompt_input_exit`). `SessionEnd` fires exactly once at real shutdown — unlike `Stop`, which fires after every LLM turn.

`compound-loop` on `Stop` is gated by `debounce_seconds` and `reprocess_min_growth_seconds` to bound worker cost. Those gates are correct during a session and wrong at its end: the last minutes of work can fall into a window where neither the gate nor the classifier in `context-inject` flags the handoff as stale, and the next session reads an out-of-date snapshot. The `session-end` hook is the fix.

**What it does:**

1. Check `compound_loop.enabled`; bail if disabled.
2. Find the latest session JSONL for the current cwd.
3. Call `should_queue_task(..., force=True)` — bypasses debounce and the growth gate; the helper still respects the `force` flag as the one intersection point between the two producers.
4. Drop the task file and spawn the worker exactly like the Stop-hook producer.

The worker is the same, the prompt is the same, the persistence layer is the same. Only the gating differs. See [ADR-019](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/019-handoff-session-end-freshness.md) for the trade-off analysis.

**Opting in** — users wire the hook into their `settings.json` the same way as the others. Example:

```json
{
  "hooks": {
    "SessionEnd": [
      {"matcher": "", "hooks": [{"type": "command", "command": "$HOME/.local/bin/lh hook session-end"}]}
    ]
  }
}
```

A harness-agnostic fallback is also available as a CLI command: `lh knowledge handoff-now` runs the same force path on demand. Useful before `/compact`, before closing a terminal without `/exit`, or on Claude Code builds that predate the `SessionEnd` event.

## How the five hooks complement each other

The magic is the composition, not any single hook. A full session lifecycle:

```
┌──────────────────────┐      ┌──────────────────────┐
│  SessionStart         │──►   │ context-inject       │
│                       │      │ reads: Git, memory,  │
│                       │      │   sessions/, jsonl,  │
│                       │      │   lazynorth          │
│                       │      │ writes: stdout       │
└──────────────────────┘      └──────────────────────┘
              │
              │  user ↔ agent conversation
              ▼
┌──────────────────────┐      ┌──────────────────────┐
│  PreCompact           │──►   │ pre-compact          │
│  (when context fills) │      │ reads: transcript    │
│                       │      │ writes: compact-     │
│                       │      │   backups/,          │
│                       │      │   memory/pre-compact │
│                       │      │   -summary.md        │
└──────────────────────┘      └──────────────────────┘
              │
              │  session continues
              ▼
┌──────────────────────┐      ┌──────────────────────┐
│  Stop                 │──►   │ session-export       │
│                       │      │ writes:              │
│                       │      │   <knowledge>/       │
│                       │      │   sessions/          │
│                       │      │                      │
│                       │──►   │ compound-loop        │
│                       │      │ (queues task,        │
│                       │      │  spawns worker)      │
│                       │      │ writes:              │
│                       │      │   decisions.jsonl,   │
│                       │      │   failures.jsonl,    │
│                       │      │   handoff.md,        │
│                       │      │   learnings/*.md     │
└──────────────────────┘      └──────────────────────┘
              │
              │  user types /exit or /clear
              ▼
┌──────────────────────┐      ┌──────────────────────┐
│  SessionEnd           │──►   │ session-end          │
│                       │      │ forces compound-loop │
│                       │      │ without gates        │
│                       │      │ so handoff.md        │
│                       │      │ reflects the         │
│                       │      │ session's final state│
└──────────────────────┘      └──────────────────────┘
```

The next `SessionStart` then reads `handoff.md`, `pre-compact-summary.md`, the last session export, and the tail of `decisions.jsonl` / `failures.jsonl`. That is the loop: every session **produces** memory that the next session **consumes**.

## Writing your own hook

Minimum viable user hook — `~/.config/lazy-harness/hooks/my_hook.py`:

```python
#!/usr/bin/env python3
"""My custom SessionStart hook."""
import json
import sys

def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        payload = {}

    # Do your work. Touch the filesystem, call an API, whatever.
    # But: always exit 0, and keep it fast.

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "Hello from my_hook",
        }
    }
    print(json.dumps(output))

if __name__ == "__main__":
    main()
```

Register it in `config.toml`:

```toml
[hooks.session_start]
scripts = ["context-inject", "my_hook"]
```

Then:

```bash
lh deploy         # regenerates the agent's hook config
lh hooks list     # confirms your hook resolved
lh hooks run my_hook --event session_start    # dry-run it with a fake payload
```

Hooks are ordered within an event. They run sequentially in the order you declared. A hook cannot cancel the ones after it — there is no hook-abort semantic, by design.

## Observability

Every built-in hook appends a line to `~/.claude/logs/hooks.log` with its name, the cwd, and what it did (or why it skipped). The compound-loop worker logs to `~/.claude/logs/compound-loop.log`. Both files rotate in place once they exceed 100 KB, keeping the last 500 lines.

`lh status hooks` surfaces a summary view over `hooks.log` so you do not have to tail it by hand.
