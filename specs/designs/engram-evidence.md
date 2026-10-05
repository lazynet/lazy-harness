# Engram compatibility probe evidence

**Historical scope (2026-09-24):** §5.2 item 1 of `specs/designs/2026-09-24-engram-2-migration.md` — probe
the exact `engram save` call `engram-persist` makes, under 2.1.0, before the
version pin bumps. Every claim below carries the command that produced it. The
live install and live DB (`/opt/homebrew/bin/engram`, `~/.engram/engram.db`)
were never modified — only read via `sqlite3 ... ".backup"`.

## 2026-09-24 — darwin/arm64 2.1.0 tarball vs. a copy of the live Mac DB

### Binary provenance

```
$ gh release download v2.1.0 -R Gentleman-Programming/engram \
    -p 'engram_2.1.0_darwin_arm64.tar.gz' -p 'checksums.txt'
$ shasum -a 256 engram_2.1.0_darwin_arm64.tar.gz
b9167999ba6deca652e367bd7d44766afa33430ab93b01f7cc0be42e6364d806  engram_2.1.0_darwin_arm64.tar.gz
$ grep darwin_arm64 checksums.txt
b9167999ba6deca652e367bd7d44766afa33430ab93b01f7cc0be42e6364d806  engram_2.1.0_darwin_arm64.tar.gz
```

Matches. Extracted, `./engram --version` → `engram 2.1.0`.

### DB copy provenance

```
$ sqlite3 ~/.engram/engram.db ".backup '<scratch>/data-git/engram.db'"
# 0.10s user 0.58s system — 0.82s total, on the live 410 MB DB
$ sqlite3 <scratch>/data-git/engram.db 'PRAGMA integrity_check;'
ok
$ sqlite3 <scratch>/data-git/engram.db 'PRAGMA user_version;'
0
```

All probes below ran with `ENGRAM_DATA_DIR=<scratch>/data-git`, never against
`~/.engram/engram.db`.

### First open (schema migration + FTS rebuild) — timed

```
$ time ENGRAM_DATA_DIR=<scratch>/data-git ./engram save \
    "probe: engram2 migration test (git cwd)" '{"probe":"git-cwd", ...}' \
    --type decision --project lazy-harness --scope project
engram: session ownership does not match write project: session "manual-save-lazy-harness" belongs to "lazy-knowledge", not "lazy-harness"
14.29s user 2.99s system 95% cpu 18.15s total
exit 1
```

**Observed:** first open took ~18s wall (FTS rebuild + schema migration to
`user_version=1`), well inside `SAVE_TIMEOUT_SECONDS=30`
(`src/lazy_harness/knowledge/engram_persist.py:26`) — a single slow-but-not-
timing-out run, not the steady state. **Expected per the plan** (§1.1: "first
open is a full reindex; expect a slow first start"): matches.

This same invocation also surfaced the finding below — it is a real behaviour
change, not a probe artifact.

### Finding: new session-ownership check hard-fails on 4 pre-existing rows

2.1.0 resolves the deterministic session id `manual-save-<project>` and, if it
already exists, requires its stored `sessions.project` to equal the incoming
`--project`. `store.go`'s new `ownership_mode`/`runtime_lease_expires_at`
columns are `NULL` on every row a 1.20.0 binary ever wrote, but the *project*
column itself already existed in 1.20.0 and, for a handful of rows, does not
match the project name the session id encodes:

```
$ sqlite3 <scratch>/data-git/engram.db \
    "SELECT id, project FROM sessions WHERE id LIKE 'manual-save-%' AND id != 'manual-save-' || project;"
manual-save-lazy-harness                  lazy-knowledge
manual-save-memory                        lazy-knowledge
manual-save-gitlab-backstage-mvp-destino  ms-backstage
manual-save-Archon                        archon
```

**Consequence:** on the Mac, once the binary is 2.1.0, `engram save ... --project lazy-harness ...`
— i.e. every `engram-persist` Stop-hook run for the `lazy-harness` project
itself — returns exit 1 and writes nothing, until this row is fixed. The other
three rows block their own projects the same way. This predates the migration
(these rows exist in the current 1.20.0-written DB) and is **not** a
lazy-harness code defect — `_resolve_project_key()` correctly returns
`lazy-harness` for this repo; the mismatch is a legacy data quality issue in
the store itself. `rescue-ownership` does not fix it: both the CLI
(`engram projects rescue-ownership`) and the HTTP route
(`POST /projects/rescue-ownership`) call `Store.RescueNullProjectOwnership`,
which only repairs sessions whose `project` is empty and blocks these four as
owned by another project. Deleting or renaming the rows is ruled out too:
`observations.session_id` and `user_prompts.session_id` reference
`sessions(id)`. The fix, tested on a copy of the migrated Mac DB, is
`UPDATE sessions SET project = <canonical suffix> WHERE id = <id>` for each
mismatched `manual-save-*` row; `observations.project` is a separate per-row
column the update never touches. It runs as a step of the Mac host migration
(§5.4 of the plan), right after the binary swap. `manual-save-Archon` cannot
block a save — `cmdSave` lowercases the project before building the id — so
fixing it is hygiene only.

The CT `agents` DB's baseline `engram doctor` was clean (plan §4, all four
checks "ok"), so this specific pattern is unlikely there, but it was not
directly queried on that host as part of this probe.

### Happy path — clean project key, no pre-existing collision

```
$ ENGRAM_DATA_DIR=<scratch>/data-git ./engram save \
    "probe: engram2 migration test (clean project)" '{"probe":"clean-project", ...}' \
    --type decision --project engram-migration-probe --scope project
Memory saved: #24437 "probe: engram2 migration test (clean project)" (decision)
exit 0
```

```
$ sqlite3 <scratch>/data-git/engram.db \
    "SELECT id, project, ownership_mode, directory FROM sessions WHERE id = 'manual-save-engram-migration-probe';"
manual-save-engram-migration-probe|engram-migration-probe|project_owned|/Users/lazynet/repos/lazy/lazy-harness/.worktrees/engram2
$ sqlite3 <scratch>/data-git/engram.db \
    "SELECT id, title, type, project FROM observations WHERE id = 24437;"
24437|probe: engram2 migration test (clean project)|decision|engram-migration-probe
```

**Observed:** exit 0, stdout `Memory saved: #N "<title>" (<type>)`, new session
created with `ownership_mode = project_owned`. **Expected per the plan** (§1.2:
"the exact call `engram-persist` makes ... is still accepted ... each save now
creates or reuses a `manual-save-<project>` session with `project_owned`
ownership"): matches.

### Non-git cwd

```
$ mkdir -p <scratch>/nongit-cwd && cd <scratch>/nongit-cwd
$ ENGRAM_DATA_DIR=<scratch>/data-git ./engram save \
    "probe: engram2 migration test (non-git cwd)" '{"probe":"non-git-cwd", ...}' \
    --type failure --project engram-migration-probe --scope project
Memory saved: #24438 "probe: engram2 migration test (non-git cwd)" (failure)
exit 0
```

**Observed:** identical outcome from a non-git cwd. **Expected per the plan**
(§1.2: "with an explicit `--project` resolution cannot be ambiguous"): matches
— cwd is irrelevant to `engram save` once `--project` is given, so
`_resolve_project_key()` (`hooks/builtins/engram_persist.py:20-43`, unchanged
by this migration) remains the only thing that needs to resolve correctly, and
it already has its own test coverage.

### Titleless save — defensive-only path

```
$ ENGRAM_DATA_DIR=<scratch>/data-git ./engram save "" '{"probe":"empty-title", ...}' \
    --type decision --project engram-migration-probe --scope project
stderr: engram: observation title is required
exit 1
```

**Observed:** matches the plan's "titleless saves are rejected" (§1.2).
**Irrelevant to this repo in practice:** `_build_title()`
(`src/lazy_harness/knowledge/engram_persist.py:123-129`) never produces an
empty string — it falls back to `f"{kind}@{ts}"` when `entry["summary"]` is
absent or not a string — so `engram-persist` can never hit this path. No test
needed; noted for completeness.

### Post-migration integrity and data-loss check

```
$ sqlite3 <scratch>/data-git/engram.db 'PRAGMA integrity_check;'
ok
$ sqlite3 <scratch>/data-git/engram.db 'PRAGMA user_version;'
1
$ sqlite3 <scratch>/data-git/engram.db \
    "SELECT (SELECT COUNT(*) FROM observations), (SELECT COUNT(*) FROM observations WHERE deleted_at IS NULL), (SELECT COUNT(*) FROM sessions), (SELECT COUNT(*) FROM user_prompts);"
24426|12667|6010|5639
```

Baseline snapshot (plan §4, captured earlier the same day, before this probe's
3 writes and before ~2h of further live agent activity on the Mac):
observations 24 410 total / 12 651 live, sessions 6 001, prompts 5 629. Every
metric here is ≥ baseline (the gap beyond the probe's own 2 successful saves
is ordinary session activity between the baseline capture and this `.backup`).
No shrinkage anywhere — consistent with "no data loss" (plan §5.5).

## `lh doctor` smoke — §5.2 item 5

Not run against the real 2.1.0 install (the live Mac binary stays 1.20.0
until the host migration itself). Simulated instead: the scratch 2.1.0
binary prepended to `PATH`, and `LH_CONFIG_DIR` pointed at a scratch copy of
the real `config.toml` with `[memory.engram].version` bumped to `"2.1.0"`
(everything else, including the real `binary` path and `enabled = false`,
left as on the Mac) — read-only, no real config or DB touched.

```
$ PATH=<scratch>/engram-probe:$PATH LH_CONFIG_DIR=<scratch>/lh-doctor-config uv run --frozen lh doctor
...
  · engram     (memory.engram) v2.1.0
      Set [memory.engram].enabled = true to activate.
```

No `(pin ...)` drift suffix — before this pin bump, the same run reported
`v2.1.0 (pin 1.20.0)`. `graphify`'s unrelated pin drift (`v0.9.61 (pin
0.9.41)`) still shows in the same output, confirming the doctor's drift
logic itself was exercised, not just silenced.

## Verdict

`engram save <title> <content> --type T --project P --scope project` — the
exact contract `engram-persist` depends on — behaves under 2.1.0 exactly as
§1.2 of the plan describes, for both git-worktree and non-git cwds, and the
migration itself is safe on a DB copy (integrity ok, `user_version` stamped,
no row-count regression). The one behaviour change with a real consequence is
the new session-ownership check, which will need four pre-existing session
rows fixed on the Mac (one of them `lazy-harness` itself) as part of that
host's migration step, independent of anything in this repo's code.

## 2026-10-05 — 3.0.0 real-store preflight

Evidence supplied by the separate preflight unit, executed before the support
pin change. This section records copied-store observations, not a deployed
upgrade. Host-specific paths and identifiers are normalized below. The older
2.1.0 findings above describe their dated snapshot, not current deployment state.

### Provenance and isolation

Target: [v3.0.0](https://github.com/Gentleman-Programming/engram/releases/tag/v3.0.0),
commit `15a2f78885d7ad8ced23b2d1d88383e9bb472c17`, Claude plugin `0.1.5`.
Release archive checksums were independently rechecked:

```text
engram_3.0.0_darwin_arm64.tar.gz: OK
54e080ed64a1d1b7b8a5d59e5a6d17100adbd69a6aafbb73d270dbeb37c03266
engram_3.0.0_linux_amd64.tar.gz: OK
22bbfd81ee9071a04d446f653842c383a3101b594e8829519a63a7c747602e69
```

SQLite online-backup snapshots of two real stores were hashed and retained as
read-only baselines. Each version ran on a separate fresh copy with isolated
`HOME`, `ENGRAM_DATA_DIR`, `ENGRAM_NO_UPDATE_CHECK=1` and
`ENGRAM_CLOUD_AUTOSYNC=0`. Linux probes ran both on tmpfs and on the same local
ZFS filesystem as that host's live store. The Darwin store used local APFS.
The live binaries and registrations were unchanged. Closing the Linux online
backup checkpointed its live WAL; counts, base-column digests and schema objects
were verified unchanged. A read-only backup source avoids that side effect.

### Migration and shipped persistence

The preflight's `runcopy.sh HOSTDIR LABEL BINARY` copied each baseline, executed
`doctor --json` twice, then used SQLite backup and `dbstat.py` to compare counts,
schema objects and base-column digests. Both stores retained every pre-existing
table count, live count and digest across first open and reopen. Integrity was
`ok`, and `user_version` remained `1`. Migration added one empty
`prompt_source_confirmations` table, its autoindex, three explicit indexes and
nine TEXT columns; an unchanged stamp does not mean an unchanged schema.

The executed `persist_probe.py ROOT BASELINE_DB BINARY PROJECT` loaded the
installed harness 0.83.5 `EngramPersister`. On a fresh pre-doctor copy it saved
one decision and one failure, appended and saved another pair, then ran with no
new input. It checked exact stored content, project/type/scope, row deltas and
JSONL byte offsets. The shipping call remained:

```text
engram save <title> <JSON-content> --type decision|failure --project <project> --scope project
CHECKS {"first_saved_2": true, "second_saved_2": true, "third_noop": true, "cursor_complete": true, "exact_4_rows": true, "contents_exact": true, "types_project_scope": true, "obs_delta_4": true, "all_saves_rc0": true}
VERDICT PASS
```

| 3.0.0 execution | First pair, seconds | Steady pair, seconds | Result |
| --- | --- | --- | --- |
| Darwin arm64, APFS store copy | 0.215 / 0.137 | 0.138 / 0.134 | 4 exact rows, complete cursor, third pass no-op |
| Linux amd64, ZFS store copy | 0.129 / 0.078 | 0.069 / 0.080 | Same checks; every save stderr empty |

First save included migration and stayed below the persister's 30-second
timeout. No CLI save adaptation was established. CLI `save` accepts a new
explicit project on both 2.1.0 and 3.0.0; MCP `mem_save` has a different contract.

### Mutation and plugin boundaries

Actual stdio MCP `tools/list` returned 19 agent tools on both releases.
`mem_update.required` changed from `[id]` to `[id, expected_project]`.
Missing, blank and wrong owners were rejected on 3.0.0 without changing the row
hash or revision count; correct owner updated the row and revision `1` to `2`.
2.1.0 applied the same invalid-owner calls as a negative control. Sync was not
enrolled, so unchanged sync counts alone do not discriminate a rejection.
Separate upstream HTTP probes observed missing-owner 400, wrong-owner 409 and
correct-owner 200. The mirror builds no MCP/HTTP update or delete payloads.

Isolated plugin scripts confirmed authoritative session binding, rejected
unreachable/mismatched/missing/ended session cases, and replayed a bound write
through real MCP. Plugin 0.1.5 made no SessionStart setup call. Plugin 0.1.3 with
3.0.0 made no registration change when the entry matched exactly; differing
entries produced a conflict. These probes used a recorder stub for Claude,
so they do not verify Claude's dispatcher, matcher, plugin-root expansion or
the deployed Stop hook. The Homebrew canonical-command mapping was checked in
source only; a real 3.0.0 keg was not installed during preflight.

Binary downgrade/reopen tolerated a prompt-bearing copy with reconciled counts,
but locally captured prompts left the new sync-identity columns NULL. The
partial unique index with populated values and cloud/sync paths were not tested.
Production rollback therefore remains a frozen DB plus its matching cursor
trees, restored together. No repair, deduplication or project merge was run.

**Verdict:** GO for a supervised Linux canary. Live per-profile session/Stop
smoke, fresh freeze/count baselines, installed binary/plugin read-back and the
observation window remain rollout gates. This evidence supports the harness
default pin change, without certifying deployment or rollback.
