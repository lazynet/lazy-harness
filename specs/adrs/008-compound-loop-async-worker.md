# ADR-008: Compound loop runs in an async background worker, not in the Stop hook

**Status:** accepted
**Date:** 2026-04-13

## Context

The compound loop is the feedback mechanism that turns finished sessions into persisted memory ([memory model](../../why/memory-model.md)). Every time a session ends, the harness should:

1. Locate the session's JSONL transcript.
2. Apply filters so trivial sessions (tiny, non-interactive, already-processed, headless `claude -p`) are skipped.
3. Gather existing decisions / failures / learnings to avoid re-generating duplicates.
4. Call a headless Claude (`claude -p`) with a carefully tuned prompt, asking it to extract decisions, failures, learnings, and handoff items.
5. Parse the JSON response and persist into `decisions.jsonl`, `failures.jsonl`, `learnings/YYYY-MM/*.md`, and `memory/handoff.md`.

Steps 4 and 5 can take 30–120 seconds and call another LLM. The naive implementation — do all of this inside the `Stop` hook — freezes Claude Code on session close, breaks cleanly on timeout, and couples the user-visible UX directly to an external subprocess.

## Decision

Split the compound loop into **a fast synchronous producer (the hook) and a slow asynchronous consumer (the worker)**, with a file-based queue between them.

- **Producer — `src/lazy_harness/hooks/builtins/compound_loop.py`.** Runs inside Claude Code's `Stop` hook. All it does:
  1. Read config, check `compound_loop.enabled`, bail if disabled.
  2. Locate the session JSONL for the current project.
  3. Apply debounce (`debounce_seconds`) and de-dup checks against the queue and the `done/` directory.
  4. Drop a task file (`<timestamp>-<short_id>.task`) into `~/.claude/queue/` with `key=value` metadata.
  5. `subprocess.Popen` the worker as a detached process (`start_new_session=True`, stdin `/dev/null`, stdout/stderr redirected to `~/.claude/logs/compound-loop.log`).
  6. Exit 0 immediately. The whole producer step takes tens of milliseconds.

- **Consumer — `src/lazy_harness/knowledge/compound_loop_worker.py`.** Runnable via `python -m`. Drains the queue under an `fcntl.flock` single-instance lock (`~/.claude/queue/.worker.lock`). For each task:
  1. Parse metadata (`parse_task`).
  2. Guardrails: session JSONL exists, `is_interactive_session`, `count_user_chars >= min_user_chars`, `min_messages` met.
  3. Gather existing decisions / failures / learnings via `collect_existing_*`.
  4. Build the prompt with `build_prompt` (ported verbatim from the predecessor — the prompt is calibration, not code).
  5. `invoke_claude` calls `claude -p --model <model> --output-format text` with a configurable timeout.
  6. `parse_response` strips fences and extracts the first balanced JSON object.
  7. `persist_results` writes atomically into `decisions.jsonl`, `failures.jsonl`, learnings markdown files, and `handoff.md`.
  8. Task file is moved to `queue/done/`.

- **Queue contract.** The queue is just files. Task filenames encode timestamp and short session ID. The `done/` subdirectory is the authoritative "already processed" signal. No database, no locks other than the worker's single-instance `flock`.

- **Failure policy.** The worker must never crash the queue. Any exception processing one task is logged and the task is moved to `done/` anyway, so a poison task cannot block future sessions.

- **Single-instance enforcement.** The worker holds an exclusive `flock` on `.worker.lock`. If a second invocation tries to start (e.g. two sessions close back-to-back), it sees `BlockingIOError` on the `LOCK_EX | LOCK_NB` acquisition, logs "another worker is running", and exits 0 — the already-running worker will pick up the new task on its current drain loop.

## Alternatives considered

- **Everything inline in the Stop hook.** Simplest code. Freezes Claude Code for up to `timeout_seconds` (default 120). Rejected on UX grounds immediately.
- **Thread inside the Stop hook.** Stop hooks exit and are reaped; a thread spawned inside one has no guarantee of completing. Rejected.
- **Long-lived `lh` daemon with a socket.** Would let us skip the subprocess spawn per event, but introduces a daemon lifecycle the rest of the framework doesn't need (see [ADR-006](006-hooks-subprocess-json.md) for the broader objection to daemons).
- **Third-party job queue (Redis, SQLite with `apscheduler`, systemd timers).** Overkill for a single-user tool. File-based queue is debuggable by `ls`, requires no installation, and survives cleanly across framework upgrades.
- **Cron / launchd drain.** Considered for Phase 5 / the `delta-by-index` idea in the backlog, but for v1 the on-demand spawn matches the "one session ends, one task runs" mental model best.

## Consequences

- Session close is instant from the user's perspective. The Stop hook is the fast path; the expensive LLM call is deferred.
- Logs are split by concern: `hooks.log` for the producer, `compound-loop.log` for the worker. Both rotate by size in-place (`_rotate_log` trims to `keep_lines=500` when the file exceeds `max_bytes`).
- The worker is unit-testable without running `claude` — `process_task` takes an `invoke` callable that tests substitute with a canned response.
- Debounce and "already processed" are belt-and-suspenders: a session that closes twice in short succession gets a single task queued (`is_debounced`) and a session whose task was already moved to `done/` is skipped on the second attempt (`is_already_processed`).
- The prompt itself is ported verbatim from the predecessor's bash worker. The docstring in `build_prompt` flags this explicitly: the prompt is calibration developed against hundreds of real sessions, and rewording it without re-tuning would silently degrade output quality.
- Atomic writes (`_atomic_write` — tempfile + `os.replace`) are used for all markdown learnings. This is required whenever the learnings directory lives under iCloud/Dropbox: those syncers observe the `rename` event atomically, unlike the `open-write-close` window, which can race with sync.
- If `claude -p` is not on the PATH, `invoke_claude` returns `None` and the task is marked skipped with a logged reason. This is deliberate — the worker is "best-effort memory enrichment", not a hard requirement.
