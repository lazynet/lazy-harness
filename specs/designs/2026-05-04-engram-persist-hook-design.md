# Engram persist built-in hook — design

**Date:** 2026-05-04
**Status:** approved (pending implementation)
**Related:** ADR-006 (hooks-subprocess-json), ADR-008 (compound-loop-insight-capture), ADR-027 (memory-model-five-layer)

## Context

The five-layer memory model documented in `~/.claude/CLAUDE.md` and ADR-027 lists Engram as the **episodic raw** layer, fed automatically at session boundaries via tools such as `mem_save` and `mem_session_summary`. The framework documentation also states, under "Persistencia al cierre", that the Stop hook persists notable sessions to Engram with `engram save`.

A `/audit-harness` run on 2026-05-04 confirmed that this is **not** what the harness actually does. Of the seven built-in hooks shipped in lh 0.15.4, **zero** invoke the `engram` CLI or any `mem_*` MCP tool. Engram works only when the agent calls it manually, which is unreliable in practice: of eleven Engram projects across the user's repos, only one has a session record. The remaining ten contain a single bootstrap observation each.

The gap is a documentation/implementation mismatch. Either the docs need to be lowered to match status quo (Engram is opt-in manual), or the harness needs a deterministic write path that mirrors learnings to Engram on every Stop. This spec implements the second option.

## Decision

Add a built-in hook `engram-persist` that runs on every `Stop` event, after `compound_loop.py`. Its job is to **mirror** every new entry written to `decisions.jsonl` and `failures.jsonl` into Engram via the `engram save` CLI, with exactly-once semantics enforced by a per-file byte cursor.

The hook is deliberately a one-way mirror. It never reads from Engram, never edits the JSONL files, and never blocks the Stop chain on Engram failures.

### Why per-entry, not per-session

Three options were evaluated:

1. **Per-entry mirror** (this design) — every JSONL line becomes one Engram observation.
2. **Per-session summary** — one Engram observation at SessionEnd with an aggregated summary.
3. **Hybrid** — both.

Per-entry was selected because it preserves a 1:1 mapping with the existing JSONL artifacts already trusted as the human-reviewable source of truth. It allows Engram queries like `engram search "supersedes"` to surface the exact decision, not a session-level paraphrase. It introduces no new aggregation logic. If session summaries are wanted later, they can be added without changing this hook.

### Why Stop, not SessionEnd

`compound_loop.py` runs on Stop and is the producer of the new JSONL entries. Running `engram-persist` immediately after — in the same Stop chain — is the smallest possible window between "entry written to JSONL" and "entry mirrored to Engram". A SessionEnd-based design would leave entries un-mirrored for the duration of an active session.

### Project key — single canonical name

The audit observed Engram fragmenting the same repo across two project keys (`lazy-harness` and `lazynet/lazy-harness`) because Engram's auto-detection prefers the git remote `<org>/<repo>` slug, falling back to the cwd basename. To prevent further fragmentation, the hook always passes `--project <basename>` derived from `git rev-parse --show-toplevel`, falling back to `Path.cwd().name`. This is a forced canonical form: even if an agent later runs `engram save` without `--project`, the hook's writes remain stable.

A backfill consolidation (`engram projects consolidate --all`) is not part of this design — that is a one-time admin action the user runs separately.

### Cursor — per-file byte offset

Two cursor strategies were considered:

| Strategy             | Pro                                  | Con                                                            |
|----------------------|--------------------------------------|----------------------------------------------------------------|
| Per-file byte offset | Trivial; resilient to JSONL formats  | Sensitive to file truncation (handled below).                  |
| Per-entry hash       | Resilient to truncation              | Requires hashing every line; complexity for marginal benefit.  |

Per-file byte offset is sufficient because the JSONL files are append-only by contract (compound_loop never rewrites lines). A truncation event (e.g. user manual edit) is detected by `offset > len(file)` and triggers a cursor reset to `0` plus a warning.

### Save success defines cursor advance

The cursor advances **only after** `engram save` returns exit code 0 for that entry. If a save fails, the cursor stays put for that entry and the next Stop retries it. Malformed JSONL lines do advance the cursor (they can never be parsed) and are logged as `skipped_malformed`.

This guarantees:

- **At-least-once delivery** of every parseable entry.
- **No blocking** on a single bad entry (malformed lines skip).
- **Self-healing**: if Engram is temporarily unavailable, the next successful Stop catches up the backlog.

## Components

1. **`src/lazy_harness/hooks/builtins/engram_persist.py`** — thin wrapper. Reads stdin payload (only `cwd` is consulted), resolves `memory_dir` and `logs_dir` from `CLAUDE_CONFIG_DIR`, computes the canonical project key, instantiates `EngramPersister`, runs it, exits 0 unconditionally. Pattern mirrors the existing builtins.
2. **`src/lazy_harness/knowledge/engram_persist.py`** — core logic. Defines `EngramPersister`, `PersistResult`, `EntryKind`. Subprocess invocation, cursor management, metrics emission. No CC payload knowledge, no environment lookups — pure I/O against paths it is given. This separation keeps unit tests free of subprocess and stdin plumbing.
3. **`src/lazy_harness/hooks/loader.py`** — register `"engram-persist": "lazy_harness.hooks.builtins.engram_persist"` in `_BUILTIN_HOOKS`.
4. **`tests/unit/test_engram_persist.py`** — unit tests for `EngramPersister` (subprocess mocked via `unittest.mock.patch`).
5. **`tests/unit/test_builtin_engram_persist.py`** — integration test: real subprocess invocation against a stub `engram` shim on `PATH`, asserts exit 0 and stdin handling.
6. **`specs/adrs/029-engram-persist-deterministic-mirror.md`** — new ADR recording the decision.
7. **`specs/adrs/README.md`** — index entry for ADR-029.

**Out of scope for this PR**: shipping a default `[hooks.session_stop]` chain that includes `engram-persist`. The repo's `templates/config.toml.default` is intentionally minimal and ships no hooks chain at all; users opt in by editing their own `~/.config/lazy-harness/config.toml`. The migration path for existing users is documented below.

## Data flow

```
Stop event (Claude Code)
        │
        ├─▶ session_export.py    (existing)
        ├─▶ compound_loop.py     (existing)
        │       │
        │       ▼
        │   appends to:
        │   <memory_dir>/decisions.jsonl
        │   <memory_dir>/failures.jsonl
        │
        └─▶ engram_persist.py    (NEW)
                │
                ▼
            load <memory_dir>/engram_cursor.json
                │
                ▼
            for each file in [decisions.jsonl, failures.jsonl]:
                seek to cursor.offset[file]
                for each new line:
                    parse JSON
                    if malformed:
                        log skipped_malformed
                        advance offset
                        continue
                    invoke: engram save <title> <content> --type <decision|failure>
                                         --project <canonical> --scope project
                    if exit 0:
                        advance offset
                        persist cursor (atomic write via tempfile + rename)
                    else:
                        log error to engram_persist.log
                        leave offset unchanged
                        break inner loop  # avoid pile-up of failures this run
                │
                ▼
            append run-summary line to engram_persist_metrics.jsonl
                │
                ▼
            exit 0  (always, even on partial failure)
```

The hook reads stdin for protocol consistency with the engine but extracts only the `cwd` field (used to resolve `memory_dir`).

## Engram CLI invocation contract

For every parseable JSONL entry the hook runs:

```
engram save \
  <title> \
  <content> \
  --type <decision|failure> \
  --project <canonical-project-key> \
  --scope project
```

Field derivation:

| CLI arg     | Source                                                                          |
|-------------|---------------------------------------------------------------------------------|
| `<title>`   | `entry.summary` (truncated to 200 chars). Fallback `f"{entry.type}@{entry.ts}"` if `summary` is missing or empty. |
| `<content>` | `json.dumps(entry, sort_keys=True)` — full original entry body                   |
| `--type`    | `decision` for entries from `decisions.jsonl`, `failure` for `failures.jsonl`. The hook trusts the file, not `entry.type`, to avoid mismatches if a future writer cross-pollutes. |
| `--project` | canonical project key (see "Project key" above). Any `entry.project` field is **ignored** — the file may have been authored under a different cwd, but the persistence target is the cwd at hook time. |
| `--scope`   | always `project` (Engram's per-project bucket)                                  |

The hook does **not** pass `--topic` — topic suggestion belongs to the agent, not to a deterministic mirror.

The current JSONL entry shape (verified 2026-05-04 against `decisions.jsonl` and `failures.jsonl` produced by `compound_loop`) is:

- decisions: `{ts, type, summary, context, alternatives, rationale, project, tags}`
- failures:  `{ts, type, summary, root_cause, resolution, prevention, project, tags}`

Both share `ts`, `type`, `summary`, `project`, `tags`. The hook only reads `summary`, `type`, and `ts`; everything else is opaque and forwarded as-is in `<content>`.

If the `engram` binary is not on `$PATH` (`shutil.which("engram") is None`), the hook logs a single warning to `engram_persist.log` and exits 0 without touching the cursor or metrics file. This makes the hook safe in environments where Engram is not installed (e.g. CI containers).

## Cursor file format

`<memory_dir>/engram_cursor.json`:

```json
{
  "version": 1,
  "decisions_offset": 4523,
  "failures_offset": 1820,
  "updated_at": "2026-05-04T11:25:00Z"
}
```

Read at the start of every run. Written atomically (`tempfile.NamedTemporaryFile` in the same dir + `os.replace`) after every successful save, so a hook crash never produces a partially written cursor.

If the file does not exist, the hook treats both offsets as `0`. If the file is corrupt (JSON decode error or schema mismatch), the hook resets both offsets to `0`, logs a warning, and proceeds. Resetting may cause re-emission of already-persisted entries; Engram's own deduplication (if any) handles that — at minimum, callers querying Engram see duplicates rather than missing data, which is the safer failure mode.

## Performance markers

### Run summary (per-invocation, always)

`<logs_dir>/engram_persist_metrics.jsonl` — one line per hook run:

```json
{
  "ts": "2026-05-04T11:25:00Z",
  "event": "run",
  "duration_ms": 234,
  "subprocess_ms": 198,
  "entries_seen": {"decisions": 2, "failures": 1},
  "saved_ok": 3,
  "saved_failed": 0,
  "skipped_malformed": 0,
  "cursor_lag_bytes": {"decisions": 0, "failures": 0},
  "engram_version": "1.15.4",
  "project_key": "lazy-harness",
  "hook_version": "0.15.4"
}
```

`duration_ms` covers the whole hook run; `subprocess_ms` is the cumulative time spent in `engram save` calls. The difference identifies whether latency comes from Engram or from the hook's own code. `cursor_lag_bytes` is `len(file) - cursor.offset[file]` after the run completes; a non-zero value means entries are pending due to prior failures.

### Slow-save events (threshold-driven)

Same JSONL file. When an individual `engram save` call exceeds the slow-save threshold, an additional line:

```json
{"ts": "...", "event": "slow_save", "ms": 612, "type": "decision", "title_prefix": "first 60 chars"}
```

The threshold is exposed as `EngramPersister(slow_save_threshold_ms: int = SLOW_SAVE_THRESHOLD_MS)`, with `SLOW_SAVE_THRESHOLD_MS = 500` defined as a module-level constant in `knowledge/engram_persist.py`. Default value 500ms is based on the expected baseline of 50–200ms per save.

Two override points without further config plumbing:

- **Constructor injection**: tests pass an explicit value (covers `test_slow_save_event_emitted_above_threshold` and `test_slow_save_event_not_emitted_below_threshold`).
- **Module constant override**: importers (a wrapper, an alternative entrypoint, or a future config-driven loader) can `monkey-patch` or pass a value derived from `os.environ.get("LH_ENGRAM_PERSIST_SLOW_MS")`. The wrapper does **not** read this env var in v1 — adding it is a one-line follow-up if a real need appears.

This keeps the public knob ("change the threshold") obvious without wiring a new `[hooks.engram_persist]` config block on day one.

### Errors (text log, separate from metrics)

`<logs_dir>/engram_persist.log`. Human-readable, line-oriented, only appended on failure paths:

- `engram save` non-zero exit (with stderr capture)
- Cursor file corrupt
- File truncation detected
- Engram binary missing

Errors are split from metrics so that the metrics file stays jq-friendly and the error log stays grep-friendly. This mirrors the existing split between `decisions.jsonl` (structured) and `compound-loop.log` (human).

### `lh doctor` integration — out of scope

A doctor check that reads `engram_persist_metrics.jsonl` and surfaces drift (last run age, recent failure rate, cursor lag) was discussed but is deferred to a follow-up PR to keep this change focused. The metrics file format defined here is the contract that the doctor check will consume.

## Error handling

| Failure mode                                  | Behaviour                                                              |
|-----------------------------------------------|------------------------------------------------------------------------|
| `engram` binary not on `$PATH`                | Log warning; exit 0; no metrics line.                                  |
| `engram save` returns non-zero exit code      | Log error; do not advance cursor for that entry; break inner loop.     |
| JSONL line is malformed JSON                  | Log warning; advance cursor (line can never parse); count `skipped_malformed`; continue. |
| `engram_cursor.json` missing                  | Treat offsets as 0; proceed.                                           |
| `engram_cursor.json` corrupt                  | Reset offsets to 0; log warning; proceed.                              |
| Cursor offset > file size (truncation)        | Reset offsets to 0; log warning; proceed.                              |
| `decisions.jsonl` or `failures.jsonl` missing | Skip that file; not an error (legitimate for fresh repos).             |
| `OSError` on file read or write               | Log error; exit 0 (never crash the chain).                             |
| `JSONDecodeError` on stdin payload            | Ignore (only `cwd` is required; default to `Path.cwd()`).              |

## Testing

### Unit tests — `tests/unit/test_engram_persist.py`

`subprocess.run` is mocked via `unittest.mock.patch`. No real `engram` binary is invoked.

- `test_persists_new_decision_entries_via_engram_save` — verifies argv layout including `--type decision`, `--project`, `--scope project`.
- `test_persists_failure_entries_with_correct_type` — same for `failures.jsonl`.
- `test_advances_cursor_only_on_successful_save` — mock returns code 1; cursor unchanged on disk.
- `test_skips_already_persisted_entries` — second run with same JSONL contents triggers zero subprocess calls.
- `test_handles_missing_engram_binary_gracefully` — `shutil.which` patched to return None; no subprocess call; metrics file not written.
- `test_handles_corrupt_cursor_file` — write garbage to cursor; persister recovers with offsets=0.
- `test_handles_malformed_jsonl_line` — line with bad JSON between two valid lines; both valid lines saved; bad one counted as `skipped_malformed`; cursor advances past all three.
- `test_resets_cursor_on_truncated_file` — write cursor with offset > file size; persister resets to 0 and re-mirrors.
- `test_persists_failures_independently_from_decisions` — only one file grows between runs; cursor of the unchanged file remains intact.
- `test_breaks_inner_loop_on_save_failure` — second entry's save fails; third entry not attempted in this run; next run picks it up.
- `test_canonical_project_key_uses_basename` — git toplevel basename takes priority over cwd basename when they differ.
- `test_metrics_run_line_emitted_with_required_fields` — metrics JSONL gets a well-formed line per run.
- `test_slow_save_event_emitted_above_threshold` — fake clock pushing one save above 500ms triggers a `slow_save` line.
- `test_atomic_cursor_write` — simulate crash mid-write (file replaced via tempfile + rename) leaves only old or new content, never partial.

### Integration test — `tests/unit/test_builtin_engram_persist.py`

Invokes the wrapper as a subprocess (mirrors `test_builtin_compound_loop.py` style):

- `test_reads_payload_from_stdin_and_resolves_memory_dir` — feeds a fake CC payload, asserts hook exits 0 and writes a metrics line.
- `test_exits_zero_when_engram_save_fails` — `PATH` shimmed to a stub that returns 1; hook still exits 0.

### Fixtures

A pytest fixture creates an isolated `memory_dir` in `tmp_path` with seeded JSONL files. A second fixture creates a fake `engram` shim (a python script that records its argv to a file and exits with a configurable code) for the integration test.

## Migration / compatibility

- **Existing users** must opt in by editing their `~/.config/lazy-harness/config.toml` and appending `"engram-persist"` to `[hooks.session_stop].scripts`, then running `lh deploy hooks` to regenerate `settings.json`. The hook registry in code (`_BUILTIN_HOOKS`) is what makes the name resolvable; `lh deploy hooks` is what writes the long-form Python invocation into `~/.claude-<profile>/settings.json`.
- **Backfill on first run**: cursor offsets default to 0, so the first invocation mirrors every entry currently in `decisions.jsonl` and `failures.jsonl`. For an active project this may be tens of entries (Martin's lazy-harness memory has ~67 combined entries today). Acceptable one-time cost; the run will spend ~3–13s in subprocess if each save takes 50–200ms.
- **No template change in this PR**: `templates/config.toml.default` is the bare-minimum starter and intentionally ships no hooks. Adding a default Stop chain is an unrelated decision and out of scope.
- **Engram binary not installed**: hook degrades to no-op with a single warning. Users without Engram (e.g. CI containers) see no breakage in their Stop chain.
- **Project key fragmentation**: existing Engram projects with split keys (e.g. `lazy-harness` and `lazynet/lazy-harness`) are not consolidated by this hook. Run `engram projects consolidate --all` once before enabling the hook, then this hook's canonical-key convention prevents re-fragmentation going forward.

## Out of scope

- `lh doctor` integration (deferred to follow-up PR).
- Backfill consolidation of fragmented Engram project keys (one-time admin action; user runs `engram projects consolidate --all` separately).
- Session-level summary observations (Option B in the brainstorm; can be added later as a separate hook without changing this one).
- Configurable `--topic` / topic-key suggestion (responsibility of the agent, not a deterministic mirror).
- Configurable slow-save threshold (constant for now; revisit if real-world data shows 500ms is wrong).

## Open questions

None. All design decisions resolved during brainstorming with the user on 2026-05-04.
