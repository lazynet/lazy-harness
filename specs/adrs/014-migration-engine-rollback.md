# ADR-014: Migration engine with detect / plan / execute / rollback phases

**Status:** accepted
**Date:** 2026-04-13

## Context

The framework's parallel-bootstrap strategy ([ADR-007](007-parallel-bootstrap-migration.md)) only works if there is a real, reliable, user-runnable migration command at the end of Phase 4. "Parallel" ends with cutover — and cutover means taking an arbitrary existing predecessor installation on a user's machine and converting it into a `lazy-harness` installation without losing data and without leaving the machine in a broken state if something fails halfway.

"Do it in a bash script" was the predecessor's approach and is why the migration is a problem at all. A bash script that partially succeeds leaves no recovery path.

## Decision

Four-phase engine under `src/lazy_harness/migrate/`:

1. **Detect (`detector.py`).** Scans the filesystem for predecessor artefacts: legacy `~/.claude*` dirs, deployed hook scripts, an existing `~/.config/lazy-harness/config.toml`, profile symlinks. Produces a `DetectedState` dataclass (`state.py`) that is pure data and has no side effects.
2. **Plan (`planner.py:build_plan`).** Takes `DetectedState` + target paths and builds a `MigrationPlan` — an ordered list of `Step` instances. Every plan begins with `BackupStep` (collect everything that might be touched) and `GenerateConfigStep`. Further steps are appended based on what the detector found: `FlattenSymlinksStep` if the legacy install used symlink trees, `RemoveScriptsStep` for deployed hook scripts, etc.
3. **Execute (`executor.py:execute_plan`).** Runs each step sequentially. Each step returns a `StepResult` with status. On **any** `StepStatus.FAILED`, the executor writes the rollback log and **immediately applies it**, returning with `rolled_back=True`. On success, it still writes the rollback log, so a user can choose to roll back later.
4. **Rollback (`rollback.py`).** `write_rollback_log` serializes the executed steps to `<backup_dir>/rollback.log`. `apply_rollback_log` replays them in reverse using each step's declared inverse. Rollback is declarative — a step declares how it undoes itself at construction time, not at failure time.

Steps live under `migrate/steps/` with one file per kind (`backup.py`, `config_step.py`, `flatten_step.py`, `scripts_step.py`) and a shared `Step` protocol in `base.py`. Each step implements `execute(backup_dir, dry_run)` and returns a result recording what it did.

`dry_run=True` is a first-class mode. Every step runs its read-side, produces its intended write actions as strings, and reports them without touching disk. This is what `lh migrate --dry-run` exposes to users and is the gate we require before any real migration.

Rollback is also available as `lh migrate --rollback <backup-dir>`, which applies a previously-written rollback log even on a successful migration — a deliberate "undo" button for the user who decides the new layout was wrong.

## Alternatives considered

- **Monolithic script with ad-hoc checks.** The predecessor approach. Failures are non-recoverable because there is no structured record of what was done before the failure. Rejected.
- **Transactional filesystem (copy everything aside, operate on the copy, swap at the end).** Works in theory, fragile in practice with hardlinks, extended attributes, and external processes (Claude Code itself) watching the target directory. Rejected.
- **Database-style migrations (Alembic-style sequential versions).** Overkill for a migration that runs once per user. The shape is "detect → plan → execute", not "apply N incremental schema versions". Rejected.
- **Ship a migration tool separate from `lh`.** Discoverability dies. Users expect `lh migrate`. Rejected.
- **No backup, no rollback — trust the user to back up their home directory first.** The single biggest cause of tool adoption failure is "I ran the thing and now my setup is broken". Non-negotiable that we ship our own backup and undo path.

## Consequences

- Every migration run produces `<backup_dir>` (under `~/.local/share/lazy-harness/backups/` by default, timestamped) containing a copy of everything that will be touched and a rollback log. Recovery is `lh migrate --rollback <backup_dir>`.
- The executor's automatic rollback on failure means a broken migration always self-heals. The user sees a failure report and their system is unchanged — no "partial state" to clean up by hand.
- Adding a new step kind is one file under `steps/` plus a branch in `planner.build_plan`. The executor does not need to know about the step's specifics — it only calls `step.execute`.
- Dry run is not a flag on the executor; it is threaded through every step. Every step has to answer "what would you do?" as honestly as "do it". This is the constraint that catches bugs before the user hits them.
- The migration is idempotent in practice: after a successful migration, re-running the detector produces an empty plan (nothing left to migrate) and execution is a no-op. The selftest has a migrate-idempotence check.
- Because the backup step collects files before any mutation, it is the reason [ADR-011](011-session-export-and-classification.md) and [ADR-012](012-sqlite-monitoring.md) can be migrated across machines later — the same infrastructure will be reused when we build `lh migrate --from-snapshot` for cross-machine replication.
