# Architecture decisions

An ADR (Architecture Decision Record) captures a decision that shaped the project: the context, the options considered, and the consequences of picking one. They are written in past tense and treated as historical — new decisions get new ADRs; existing ones get annotated or superseded, not rewritten.

For the "what" and "how" of the architecture, see the architecture overview and how pages under `docs/`. This page is the index of **why** decisions were made.

## Framework ADRs

Decisions that define the `lazy-harness` project itself.

| # | Status | Title | Summary |
|---|---|---|---|
| [001](./001-hybrid-architecture.md) | accepted | Hybrid architecture — framework + dotfile config | Split framework code (package) from personal harness content (user dotfiles). |
| [002](./002-python-uv-distribution.md) | accepted | Python 3.11+ with `uv tool install` | One language, one install command, no compilation step, Windows-feasible. |
| [003](./003-toml-config-format.md) | accepted | TOML config format | Single TOML file parsed by stdlib `tomllib`. No schema file, no DSL. |
| [004](./004-agent-adapter-pattern.md) | accepted | Agent adapter pattern | Thin protocol abstracts the ~6 things the framework actually needs from an agent. |
| [005](./005-xdg-first-paths.md) | accepted | XDG-first path resolution | Single path module with env > XDG > platform-default order. |
| [006](./006-hooks-subprocess-json.md) | accepted | Hooks as subprocess + JSON stdin/stdout | Built-in and user hooks are indistinguishable; agent spawns them, not `lh`. |
| [007](./007-parallel-bootstrap-migration.md) | accepted | Parallel-bootstrap migration | Build the replacement alongside the old system; cut over when proven. |
| [008](./008-compound-loop-async-worker.md) | accepted | Compound loop as async file-queue worker | Stop hook enqueues, detached worker processes. Session close stays instant. |
| [009](./009-profile-symlink-deploy.md) | accepted | Profile symlink deploy | Per-file symlinks from source dotfiles into the agent target dir. |
| [010](./010-pre-compact-preservation.md) | accepted | Pre-compact context preservation | Back up the transcript and distill a working-state summary before compaction. |
| [011](./011-session-export-and-classification.md) | accepted | Session export with classification | JSONL → dated markdown with project/profile frontmatter, atomic writes. |
| [012](./012-sqlite-monitoring.md) | accepted | SQLite monitoring | Single-table idempotent store, view modules per angle. |
| [013](./013-scheduler-unified-backends.md) | accepted | Unified scheduler backends | launchd / systemd / cron behind one protocol, declared once in config. |
| [014](./014-migration-engine-rollback.md) | accepted | Migration engine with automatic rollback | Detect → plan → execute → auto-rollback on failure. Dry-run is a first-class mode. |
| [015](./015-strict-tdd-workflow.md) | accepted | Strict TDD as a workflow rule | No production code without a failing test first. Non-negotiable. |
| [016](./016-knowledge-dir-qmd-optional.md) | accepted | Knowledge directory + optional QMD | Plain markdown tree; QMD is semantic search opt-in via `shutil.which`. |
| [017](./017-selftest-as-health-check.md) | accepted | Selftest as user-facing health check | `lh selftest` is not pytest — it is the on-machine configuration check. |
| [018](./018-config-discoverability.md) | accepted | Feature discoverability via `lh doctor` + `lh config <feature>` | No wizards on upgrade. `lh doctor` lists features; `lh config <feature> --init` is the opt-in wizard. |
| [019](./019-handoff-session-end-freshness.md) | accepted | Force a final compound-loop evaluation at session end | `SessionEnd` hook + `lh knowledge handoff-now` bypass the Stop-hook gates so the handoff reflects the session's final state. |
| [020](./020-post-compact-context-reinjection.md) | accepted | Post-compact hook re-injects the pre-compact summary | Mirror the PreCompact summary into the live post-compaction context with a 5-minute freshness check. |
| [021](./021-async-response-grading.md) | accepted | Async response grading via the compound-loop worker | One LLM call returns decisions/failures/learnings/handoff *and* a quality grade. Poor grades escalate to PRJ.md. |
| [022](./022-engram-episodic-memory.md) | accepted | Engram as optional episodic memory backend | New `memory/engram.py` wrapper + `[memory.engram]` config + MCP deploy gating. Mirrors the ADR-016 QMD pattern. |
| [023](./023-graphify-code-structure.md) | accepted | Graphify as optional code-structure index | New `knowledge/graphify.py` wrapper + `[knowledge.structure]` config + MCP deploy gating. Mirrors ADR-016 / ADR-022. |
| [024](./024-mcp-server-orchestration.md) | accepted | MCP server orchestration via `lh deploy` | Single seam in deploy writes `mcpServers` to each profile's `settings.json` from detected tools (QMD today, Engram/Graphify next). |
| [025](./025-doctor-features-section.md) | accepted | `lh doctor` Features section for triple stack | New `lazy_harness.features` helper + Features section in `lh doctor` listing qmd/engram/graphify with state, version, and pin. First half of ADR-018 implementation. |
| [026](./026-config-wizards.md) | accepted | `lh config <feature> --init` wizards (Fase 3b) | New `lh config` Click group + `wizards/` package with TOML deep-merge. Closes ADR-018 implementation. |
| [027](./027-memory-stack-overview.md) | accepted | Memory stack overview — five-layer model | Names the user-facing layer model that ADR-016/022/023/024 produced. No new mechanism, only canonical vocabulary. |
| [028](./028-classify-rules-configurable.md) | accepted | Configurable session classification rules | Lift the four hardcoded `_classify` rules into typed `[[knowledge.classify_rules]]` config; defaults reproduce historical behaviour. |
| [029](./029-engram-persist-deterministic-mirror.md) | accepted | Deterministic Engram mirror via Stop hook | Deterministic Engram mirror via Stop hook (engram-persist) |

### Status values

Each active ADR carries one of the following statuses in its header. The column above is the index view; the ADR file is the source of truth.

| Status | Meaning |
|---|---|
| `accepted` | Decision taken **and** embodied in code, config, or tests. Default state for a shipping decision. |
| `accepted-deferred` | Decision taken and locked, but implementation is intentionally not yet scheduled. The ADR is not incomplete — its realisation is waiting for a specific trigger documented in the ADR itself. |
| `proposed` | Written and reasoned, but not yet committed to. Open for revision. No active ADR currently holds this status. |
| `superseded-by: NNN` | Replaced by a later ADR. The record is kept for history; the pointer names its replacement. No active ADR currently holds this status. |

New decisions default to `accepted` once they ship. A decision that turns out wrong is **superseded** by a new ADR rather than edited in place.

## Legacy ADRs

The ADRs numbered 001–013 under `../archive/adrs-legacy/` preserve the predecessor project's decision history verbatim. They are kept as archival material for provenance; they are intentionally not edited to match the current nomenclature or architecture.

They live outside `docs/` entirely, so they never surface in the rendered public site. Browse them on the repo if you want the history of how the framework got to its current shape.
