# Architecture decisions

An ADR (Architecture Decision Record) captures a decision that shaped the project: the context, the options considered, and the consequences of picking one. They are written in past tense and treated as historical — new decisions get new ADRs; existing ones get annotated or superseded, not rewritten.

For the "what" and "how" of the architecture, see the [overview](../overview.md) and the [how section](../../how/hooks.md). This page is the index of **why** decisions were made.

## Framework ADRs

Decisions that define the `lazy-harness` project itself.

| # | Title | Summary |
|---|---|---|
| [001](../adrs/001-hybrid-architecture.md) | Hybrid architecture — framework + dotfile config | Split framework code (package) from personal harness content (user dotfiles). |
| [002](../adrs/002-python-uv-distribution.md) | Python 3.11+ with `uv tool install` | One language, one install command, no compilation step, Windows-feasible. |
| [003](../adrs/003-toml-config-format.md) | TOML config format | Single TOML file parsed by stdlib `tomllib`. No schema file, no DSL. |
| [004](../adrs/004-agent-adapter-pattern.md) | Agent adapter pattern | Thin protocol abstracts the ~6 things the framework actually needs from an agent. |
| [005](../adrs/005-xdg-first-paths.md) | XDG-first path resolution | Single path module with env > XDG > platform-default order. |
| [006](../adrs/006-hooks-subprocess-json.md) | Hooks as subprocess + JSON stdin/stdout | Built-in and user hooks are indistinguishable; agent spawns them, not `lh`. |
| [007](../adrs/007-parallel-bootstrap-migration.md) | Parallel-bootstrap migration | Build the replacement alongside the old system; cut over when proven. |
| [008](../adrs/008-compound-loop-async-worker.md) | Compound loop as async file-queue worker | Stop hook enqueues, detached worker processes. Session close stays instant. |
| [009](../adrs/009-profile-symlink-deploy.md) | Profile symlink deploy | Per-file symlinks from source dotfiles into the agent target dir. |
| [010](../adrs/010-pre-compact-preservation.md) | Pre-compact context preservation | Back up the transcript and distill a working-state summary before compaction. |
| [011](../adrs/011-session-export-and-classification.md) | Session export with classification | JSONL → dated markdown with project/profile frontmatter, atomic writes. |
| [012](../adrs/012-sqlite-monitoring.md) | SQLite monitoring | Single-table idempotent store, view modules per angle. |
| [013](../adrs/013-scheduler-unified-backends.md) | Unified scheduler backends | launchd / systemd / cron behind one protocol, declared once in config. |
| [014](../adrs/014-migration-engine-rollback.md) | Migration engine with automatic rollback | Detect → plan → execute → auto-rollback on failure. Dry-run is a first-class mode. |
| [015](../adrs/015-strict-tdd-workflow.md) | Strict TDD as a workflow rule | No production code without a failing test first. Non-negotiable. |
| [016](../adrs/016-knowledge-dir-qmd-optional.md) | Knowledge directory + optional QMD | Plain markdown tree; QMD is semantic search opt-in via `shutil.which`. |
| [017](../adrs/017-selftest-as-health-check.md) | Selftest as user-facing health check | `lh selftest` is not pytest — it is the on-machine configuration check. |

## Legacy ADRs

The ADRs numbered 001–013 under `decisions/legacy/` preserve the predecessor project's decision history verbatim. They are kept as archival material for provenance; they are intentionally not edited to match the current nomenclature or architecture.

They are not part of the public site navigation. You can browse them on GitHub if you want the history of how the framework got to its current shape.
