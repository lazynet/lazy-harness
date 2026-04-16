# How the memory compound loop works

The memory model describes the [what](../why/memory-model.md) — three scales (short-term, medium-term, long-term), structured stores, self-maintained project memory. This page is the **how**: how the compound loop physically turns a just-finished session into persisted, queryable memory, file by file, step by step.

If you want the design rationale, read [ADR-008 — Compound loop async worker](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/008-compound-loop-async-worker.md). This page is the mechanics.

## The loop, one step at a time

```
  session ends
       │
       ▼
┌────────────────────────┐
│ Stop hook              │     producer — runs in Claude Code's process
│ compound_loop.py       │     budget: milliseconds
│ (hooks/builtins/)      │
└────────────────────────┘
       │ drops task file
       ▼
~/.claude/queue/
  1737583912-a1b2c3d4.task
       │ spawns worker (detached)
       ▼
┌────────────────────────┐
│ compound_loop_worker   │     consumer — detached background process
│ .py                    │     budget: up to timeout_seconds (default 120)
│ (knowledge/)           │
└────────────────────────┘
       │ invokes claude -p
       │ parses JSON response
       │ atomic writes
       ▼
┌────────────────────────────────────────────────┐
│ memory/decisions.jsonl          (append)       │
│ memory/failures.jsonl           (append)       │
│ memory/handoff.md               (overwrite)    │
│ learnings/YYYY-MM/<slug>.md     (atomic)       │
└────────────────────────────────────────────────┘
       │ moves task file
       ▼
~/.claude/queue/done/
  1737583912-a1b2c3d4.task
```

Every piece is on disk and inspectable. No daemons, no shared memory, no IPC beyond the filesystem.

## Phase 1 — The Stop hook (producer)

File: `src/lazy_harness/hooks/builtins/compound_loop.py`.

When Claude Code fires the `Stop` event, the producer runs in-process with a tight budget. Its job is not to think about the session — its job is to decide "should this session be processed later, and if so, queue it".

Steps, in order:

1. **Read stdin.** The event payload is consumed and discarded — the producer does not need it. It is consumed only so Claude Code does not see a broken pipe.
2. **Load config.** `load_config(config_file())` — if it fails or `compound_loop.enabled == False`, log and exit. The loop is opt-in.
3. **Find the session JSONL.** Encode the cwd into Claude Code's project-dir convention (`/Users/x/repo` → `-Users-x-repo`), look under `<CLAUDE_CONFIG_DIR>/projects/<encoded>/`, pick the most recent `*.jsonl` by mtime.
4. **Debounce.** `is_debounced(queue_dir, session_id, debounce_seconds)` — if a task for the same session was queued within the window (default 60s), skip. This is what prevents a flapping session close from queuing the same work repeatedly.
5. **Growth gate.** `should_reprocess` — re-queue only if the session JSONL has grown past `reprocess_min_growth_seconds` (default 120) since the last `done/` task for this session. Bounds the worker cost on long active sessions where `Stop` fires after every LLM turn.
6. **De-dup against `done/`.** `is_already_processed(queue_dir, session_id)` — if a task for this session already lives in `queue/done/`, skip. Protects against re-running the hook on the same session after a backup/restore or clock skew.
7. **Drop the task file.** `create_task(queue_dir, cwd, session_jsonl, session_id, memory_dir)` writes a file named `<unix_ts>-<short_id>.task` with lines:
   ```
   cwd=/Users/x/repo
   session_jsonl=/Users/x/.claude/projects/.../<id>.jsonl
   session_id=<full-id>
   memory_dir=/Users/x/.claude/projects/.../memory
   timestamp=2026-04-13T18:32:45-03:00
   ```
8. **Spawn the worker.** `subprocess.Popen` with `start_new_session=True`, stdin `/dev/null`, stdout/stderr redirected to `~/.claude/logs/compound-loop.log`. The producer does not wait for it.
9. **Exit 0.** The whole producer phase is tens of milliseconds. Claude Code sees a clean session close.

### Why there is a second producer on `SessionEnd`

`Stop` fires after every LLM turn, so the debounce and growth gates in steps 4 and 5 exist to keep the worker cheap. They are correct for mid-session activity and wrong for the *last* few minutes of a session: if the user resolves the last pending item shortly before typing `/exit`, the final `Stop` is within the growth window and skipped, and `handoff.md` stays frozen on the earlier snapshot.

The `session-end` hook (see [`docs/how/hooks.md`](hooks.md#session-end-runs-on-sessionend)) is a second producer wired to Claude Code's `SessionEnd` event. It does everything the `compound-loop` producer does **except** apply the debounce and growth gates — it calls `should_queue_task(..., force=True)`. `SessionEnd` fires exactly once, at real session termination, so it does not need gates to be cheap.

`lh knowledge handoff-now` (below) is the same flow, invoked by hand. See [ADR-019](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/019-handoff-session-end-freshness.md) for the full decision record.

## Phase 2 — The background worker (consumer)

File: `src/lazy_harness/knowledge/compound_loop_worker.py`. Runs via `python -m lazy_harness.knowledge.compound_loop_worker`. The pure functions it calls live in `src/lazy_harness/knowledge/compound_loop.py` and are individually testable.

Steps:

1. **Single-instance lock.** `fcntl.flock` on `~/.claude/queue/.worker.lock` with `LOCK_EX | LOCK_NB`. If another worker holds it (e.g. a quick back-to-back session close), exit 0 — the in-flight worker will drain the new task.
2. **Load config, resolve learnings dir.** `_resolve_learnings_dir` honors `LCT_LEARNINGS_DIR` (back-compat env var) then falls back to `<knowledge.path>/<compound_loop.learnings_subdir>`.
3. **Drain loop.** `_drain_queue` scans `*.task` in the queue, processes each, moves it to `done/`. Continues until the queue is empty — tasks that arrived mid-drain are picked up on the next iteration before exit.
4. For each task, `process_task`:
    - **Parse metadata.**
    - **Session JSONL exists?** If not, mark skipped ("session JSONL not found").
    - **Interactive check.** `is_interactive_session` looks at line 1 of the JSONL; sessions without a `permission-mode` first record are headless `claude -p` invocations or subagent dispatches and are excluded from the loop.
    - **User-char gate.** `count_user_chars` sums the chars across all `user` messages. If under `min_user_chars` (default 200), skip — the session is too thin to distill.
    - **Message-count gate.** `extract_messages` returns (formatted_text, total_count). Skip if under `min_messages` (default 4).
    - **Collect existing memory** for de-dup prompts:
      - `collect_existing_decisions` — tail of `decisions.jsonl`
      - `collect_existing_failures` — tail of `failures.jsonl`
      - `collect_existing_learnings` — the titles of the most recent 50 learnings markdown files
    - **Build the prompt.** `build_prompt` composes a headless-Claude prompt that embeds all of the above plus the session summary. The prompt is calibration — its wording was iterated against hundreds of real sessions in the predecessor, and it is documented as load-bearing.
    - **Call Claude headlessly.** `invoke_claude` runs `claude -p --model <model> --output-format text` with `timeout=timeout_seconds`. Returns stdout, or `None` on timeout / missing binary / empty output.
    - **Parse the response.** `parse_response` strips markdown fences, then does three things in order: try raw `json.loads`, then look for the first `{` and walk a balanced-brace state machine to extract a JSON object out of a prose preamble, then give up and return `None`.
    - **Persist.** `persist_results` does the writes (next section).
5. **Move task to `done/`.** Always, even on failure. A poison task must not block the queue.

## Phase 3 — What gets written

`persist_results` takes the parsed JSON from the LLM and writes four categories of output, all using atomic writes where applicable.

### `decisions.jsonl` — medium-term episodic store

Each decision from the LLM becomes a single JSON line appended to `<memory_dir>/decisions.jsonl`:

```json
{"ts":"2026-04-13T18:32:45-03:00","type":"decision",
 "summary":"Profile deploy uses symlinks, not copies",
 "context":"We needed iterations to be instant and source to remain read-only",
 "alternatives":["copy on deploy","bind mount","direct CLAUDE_CONFIG_DIR"],
 "rationale":"Symlinks are zero-cost to update and decouple source from write-side state",
 "project":"lazy-harness","tags":["architecture","profiles"]}
```

The format is append-only and human-greppable. You can read years of decisions with `jq -r '.summary' decisions.jsonl` and see the full history of a project's choices.

### `failures.jsonl` — preventable errors

Same format, different fields:

```json
{"ts":"2026-04-13T18:32:45-03:00","type":"failure",
 "summary":"pytest collected an empty worktree",
 "root_cause":"Worktree was not gitignored; test discovery picked up shadow files",
 "resolution":"Added .worktrees/ to .gitignore and re-ran pytest from repo root",
 "prevention":"Every feature branch uses a dedicated worktree under .worktrees/ and the dir is in .gitignore",
 "project":"lazy-harness","tags":["testing","worktrees"]}
```

The `prevention` field is the critical one — this is what the `context-inject` hook surfaces in `## Recent history` on the next session start, specifically to put the prevention in the agent's face before it repeats the same mistake.

### `handoff.md` — open items for next session

`memory/handoff.md` is overwritten (not appended) with the current pending items:

```markdown
Pendiente para próxima sesión:
- finish the docs restructure
- run mkdocs build --strict before commit
```

If the LLM returns an empty handoff list, the file is **deleted** — which is why the absence of `handoff.md` at session start means "nothing left hanging", not "there was no memory".

### `learnings/YYYY-MM/YYYY-MM-DD-<slug>.md` — long-term cross-project knowledge

Each learning becomes a dedicated markdown file in the knowledge directory under `<learnings_dir>/YYYY-MM/`. The filename is date-prefixed and slugified from the title; existing files are not overwritten (learnings are write-once).

Frontmatter:

```yaml
---
title: "File-based queue is enough for single-user async"
origin: lazy-harness
origin_session: 2026-04-13
tags: ["architecture","async","queue"]
scope: universal
status: active
deprecated_by: null
deprecated_on: null
deprecated_reason: null
---
```

Body:

```markdown
## Learning
<the 1-2 sentence learning>

## Context
<one paragraph of where it applies>
```

These are the entries QMD picks up and indexes semantically. The `scope` field (`universal | backend | infra | consulting`) lets a future query say "give me infra-scoped learnings from the last year".

## De-duplication — why the same learning does not appear twice

Every worker invocation passes the current tail of decisions, failures, and learnings into the prompt with explicit anti-dup instructions ("avoid duplicates", "Do NOT repeat these or semantic equivalents"). The LLM is the dedup mechanism — a semantic filter, not a string match.

This is why `collect_existing_learnings` has a `limit` parameter (default 50): the prompt has to stay bounded, but 50 entries is enough to cover the semantic neighborhood of "what was I learning in the last few weeks".

When a genuinely duplicate learning sneaks past the LLM filter, two things catch it: the per-title filename de-dup (existing files are not overwritten), and weekly learnings review — which is a separate feature that reads the learnings directory and merges near-duplicates.

## What the loop does NOT do

- **It does not edit `MEMORY.md`.** That file is maintained by Claude Code itself during normal sessions via the auto-memory system documented in the user's `CLAUDE.md`. The compound loop owns the `.jsonl` and `learnings/` layers; `MEMORY.md` is orthogonal.
- **It does not block session close.** Everything heavy happens after the producer exits. A session that closed at 18:32:45 with a busy queue behind it will still close at 18:32:45.
- **It does not write to the knowledge directory's `sessions/` subtree.** That is `session-export`'s job. The loop only writes to `memory/*.jsonl`, `memory/handoff.md`, and `learnings/*.md`.
- **It does not fail the session if Claude is unreachable.** `invoke_claude` timing out or returning empty just marks the task skipped and moves on. Memory enrichment is best-effort by design.

## Tuning knobs

All in `config.toml` under `[compound_loop]`:

| Field | Default | Effect |
|---|---|---|
| `enabled` | `false` | Master switch. Off by default. |
| `model` | `claude-haiku-4-5-20251001` | Model used by the worker for distillation. Haiku is the cost/speed sweet spot; you can swap for Sonnet or Opus if you want deeper analysis per session. |
| `min_messages` | `4` | Sessions with fewer interactive messages are skipped. |
| `min_user_chars` | `200` | Sessions where the user typed fewer than this many characters total are skipped — covers fast "what's the weather" prompts. |
| `debounce_seconds` | `60` | Debounce window for repeat Stop events on the same session. |
| `reprocess_min_growth_seconds` | `120` | Minimum seconds of JSONL growth since the last `done/` task before a Stop event re-queues. Bounds worker cost on long sessions; the `session-end` hook and `lh knowledge handoff-now` both bypass this. |
| `timeout_seconds` | `120` | Hard timeout on the `claude -p` subprocess. |
| `learnings_subdir` | `learnings` | Subdirectory of `<knowledge.path>` where learning markdown files are written. |

Changes take effect on the next session — the producer and worker both reload config each run.

## Debugging

```bash
# Is the producer firing?
tail -f ~/.claude/logs/hooks.log

# Is the worker running?
tail -f ~/.claude/logs/compound-loop.log

# What's in the queue right now?
ls -la ~/.claude/queue/

# What has already been processed?
ls -la ~/.claude/queue/done/

# Force-run the worker now
python -m lazy_harness.knowledge.compound_loop_worker

# Queue a forced evaluation for the current session (bypass Stop-hook gates)
lh knowledge handoff-now

# Inspect recent decisions for a project
jq -c '.summary' ~/.claude/projects/-Users-me-repo/memory/decisions.jsonl | tail -10
```

If the worker is silent, check: (1) `compound_loop.enabled = true` in config, (2) the session has ≥ `min_messages` messages and ≥ `min_user_chars` chars, (3) `claude` is on the worker's PATH, (4) `claude -p --model <model>` actually works from your shell.
