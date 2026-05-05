# Architecture overview

A map of the codebase: the modules, what they own, how they talk to each other, and where the persistent state lives.

For the design rationale behind each major choice, see the [ADRs](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/001-hybrid-architecture.md). This page is the bird's-eye view.

## Two-tier architecture

`lazy-harness` is a Python package that installs via `uv tool install` and writes almost nothing outside of `~/.config/lazy-harness/`. The design has a hard boundary between:

- **Framework code** — shipped as a package, upgraded with `uv tool upgrade`. Contains zero personal content.
- **User-owned harness content** — lives under `~/.config/lazy-harness/`, versioned with the user's dotfile tool. Contains `config.toml`, `profiles/<name>/*`, optional user hooks.

The framework **reads from** the user-owned content and **deploys** it into the agent's config directory via symlinks + generated settings. The user never edits anything inside the framework package. See [ADR-001](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/001-hybrid-architecture.md).

```
┌──────────────────────────────┐          ┌─────────────────────────────────┐
│  Framework (Python package)  │          │  User-owned harness content     │
│  ~/.local/share/uv/tools/    │          │  ~/.config/lazy-harness/        │
│    lazy-harness/             │          │  ├── config.toml                │
│    └── src/lazy_harness/     │          │  ├── profiles/                  │
│        ├── cli/              │   reads  │  │   ├── personal/              │
│        ├── core/             │   ─────► │  │   │   ├── CLAUDE.md          │
│        ├── agents/           │          │  │   │   ├── skills/            │
│        ├── hooks/            │          │  │   │   └── ...                │
│        ├── knowledge/        │          │  │   └── work/                  │
│        ├── monitoring/       │          │  └── hooks/                     │
│        ├── scheduler/        │          │      └── (user hooks, opt)      │
│        ├── migrate/          │          └─────────────────────────────────┘
│        ├── selftest/         │                           │
│        ├── init/             │                           │ deploy
│        └── deploy/           │                           ▼
└──────────────────────────────┘          ┌─────────────────────────────────┐
                                          │  Agent target dirs               │
                                          │  ~/.claude-personal/  (symlinks  │
                                          │  ~/.claude-work/      + gen'd    │
                                          │  ~/.claude → default  settings)  │
                                          └─────────────────────────────────┘
```

## Package layout

```
src/lazy_harness/
├── cli/             # click subcommands — one file per `lh <command>`
├── core/            # config, paths, profiles, envrc — foundational
├── agents/          # agent adapter protocol + Claude Code adapter
├── hooks/           # hook engine + loader + built-in hooks
├── knowledge/       # session export, QMD wrapper, compound loop
├── monitoring/      # SQLite ingest, views, dashboard
├── scheduler/       # launchd, systemd, cron backends + manager
├── migrate/         # detector, planner, executor, rollback, steps/
├── init/            # interactive `lh init` wizard
├── selftest/        # runner, checks/
└── deploy/          # symlink engine, agent config generation
tests/               # mirrors src/lazy_harness/ one-to-one
templates/           # file templates (profile scaffolds, etc.)
docs/                # this site
```

Every module under `src/lazy_harness/` has a test file under `tests/` in the same shape. This is enforced by [ADR-015 (strict TDD)](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/015-strict-tdd-workflow.md).

## Foundational layer — `core/`

Everything downstream consumes the types defined here.

### `core/config.py` — typed configuration

Defines the `Config` dataclass and its subsection dataclasses (`ProfilesConfig`, `KnowledgeConfig`, `CompoundLoopConfig`, `ContextInjectConfig`, `LazyNorthConfig`, `MonitoringConfig`, `SchedulerConfig`, `HooksConfig` — the last one is a dict keyed by event name). `load_config(path)` reads TOML via stdlib `tomllib`, validates required keys, and raises `ConfigError` with a descriptive path + reason on failure. `save_config(cfg, path)` writes back through `tomli-w` and is only called by `lh init`, `lh migrate`, and `lh profile add/remove` — ordinary `lh` commands never rewrite the user's file.

Format decisions: [ADR-003 — TOML](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/003-toml-config-format.md).

### `core/paths.py` — platform-correct directories

Single source of truth for filesystem locations. Three functions (`config_dir`, `data_dir`, `cache_dir`) with identical resolution order:

1. Explicit override env var (`LH_CONFIG_DIR`, `LH_DATA_DIR`, `LH_CACHE_DIR`)
2. XDG env vars (`XDG_CONFIG_HOME`, etc.)
3. Platform default (Linux/macOS XDG defaults, Windows `%APPDATA%` / `%LOCALAPPDATA%`)

No other module computes these paths. `expand_path()` and `contract_path()` handle `~` expansion and home-dir abbreviation wherever a user-supplied path enters the system.

Design rationale: [ADR-005 — XDG-first paths](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/005-xdg-first-paths.md).

### `core/profiles.py` — profile list / add / resolve

`list_profiles(cfg)` returns `ProfileInfo` records with `exists` probing the filesystem. `add_profile` / `remove_profile` mutate the config in-place (callers save). `resolve_profile(cfg, cwd)` picks a profile by longest-matching-root, falling back to the configured default.

### `core/envrc.py`

Generates per-profile `.envrc` fragments for users who wire profile selection through direnv. Consumes `ProfilesConfig`, produces a shell snippet setting `CLAUDE_CONFIG_DIR`.

## Agent layer — `agents/`

`agents/base.py` defines the `AgentAdapter` protocol — the minimal surface the framework needs from any supported agent:

- `name` / `config_dir(profile_config_dir)` — identification and path resolution.
- `env_var()` — the environment variable the agent honors for alternate config dirs.
- `resolve_binary()` — locate the agent executable, specifically avoiding recursion into the `lh` wrapper.
- `supported_hooks()` + `generate_hook_config(hooks)` — what events exist and how to serialize them for the agent's native config format.

`agents/claude_code.py` is the only implementation today. `agents/registry.py` maps `config.toml`'s `[agent].type` value to an adapter class. Adding a new agent = one file + one registry entry, with no other code in the framework touching agent-specific concerns.

Design: [ADR-004 — Agent adapter pattern](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/004-agent-adapter-pattern.md).

## Hook engine — `hooks/`

`hooks/loader.py` resolves hook names to executable paths. Built-in hooks are looked up first (`_BUILTIN_HOOKS` dict under `hooks/builtins/`); user hooks fall through to `~/.config/lazy-harness/hooks/<name>.py`. `resolve_hooks_for_event(cfg, event)` returns the ordered list of resolved hooks for a given event name from config.

`hooks/engine.py` provides `execute_hook` + `run_hooks_for_event` — used by `lh hooks run` and the test suite. At runtime, the agent itself spawns hooks; the framework does not orchestrate them. The engine is for programmatic invocation only.

Built-in hooks:

- `compound_loop.py` — Stop producer, enqueues async worker. See [how hooks work](../how/hooks.md#compound-loop-runs-on-stop).
- `context_inject.py` — SessionStart, composes and injects context.
- `session_export.py` — Stop, exports session to knowledge directory.
- `pre_compact.py` — PreCompact, preserves working state before compaction.

Design: [ADR-006](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/006-hooks-subprocess-json.md). End-to-end mechanics: [how hooks work](../how/hooks.md).

## Knowledge layer — `knowledge/`

- `directory.py` — knowledge directory management, subdirs creation, path resolution.
- `session_export.py` — JSONL → markdown export with classification and atomic writes.
- `compound_loop.py` — pure functions for the compound loop (parse, filter, build prompt, parse response, persist). Flat module so each step is independently testable.
- `compound_loop_worker.py` — runnable via `python -m`, drains the file-based queue under `fcntl.flock`.
- `qmd.py` — optional QMD CLI wrapper, guarded by `shutil.which("qmd")`.
- `context_gen.py` — shared helpers for context composition.

Detailed flow: [how the memory compound loop works](../how/memory-compound.md) and [how the knowledge pipeline works](../how/knowledge-pipeline.md).

Design decisions: [ADR-008](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/008-compound-loop-async-worker.md), [ADR-010](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/010-pre-compact-preservation.md), [ADR-011](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/011-session-export-and-classification.md), [ADR-016](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/016-knowledge-dir-qmd-optional.md).

## Deploy engine — `deploy/`

`deploy/engine.py` has four top-level functions called by `lh deploy`:

1. **`deploy_profiles(cfg)`** — for each profile, symlink every item from `~/.config/lazy-harness/profiles/<name>/*` into `<profile.config_dir>/`. Per-file symlinks (not whole-directory), idempotent, refuses to clobber real files.
2. **`deploy_hooks(cfg)`** — resolve hooks per event, call `agent.generate_hook_config`, write the result into each profile's `settings.json`.
3. **`deploy_mcp_servers(cfg)`** — probe each detected memory-stack tool (QMD, Engram), call `agent.generate_mcp_config`, merge the resulting `mcpServers` block into each profile's `settings.json` next to `hooks`. Uninstalled tools get no entry; removed tools have their entry pruned on the next run.
4. **`deploy_claude_symlink(cfg)`** — create `~/.claude → <default profile config_dir>`.

`deploy/symlinks.py` implements `ensure_symlink` with the three states: `"created"`, `"exists"` (already points at the correct source), and `"refused"` (target is a real file or a link to somewhere else and cannot be clobbered).

Design: [ADR-009 — Profile symlink deploy](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/009-profile-symlink-deploy.md), [ADR-024 — MCP server orchestration](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/024-mcp-server-orchestration.md). Mechanics: [how profiles and deploy work](../how/profiles-and-deploy.md).

## Monitoring — `monitoring/`

Local SQLite store populated by parsing session JSONLs:

- `db.py` — single-table schema (`session_stats`) with `UNIQUE(session, model)` for idempotent re-ingestion, plus an index on `date`.
- `collector.py` — walks `<CLAUDE_CONFIG_DIR>/projects/**/*.jsonl`, extracts per-session token counts (input, output, cache_read, cache_create), computes cost against `[monitoring.pricing]`, and does `INSERT OR IGNORE` into the DB.
- `pricing.py` — cost calculation from the pricing dict.
- `views/` — one file per viewing angle (`overview`, `projects`, `profiles`, `sessions`, `tokens`, `cron`, `hooks`, `memory`, `queue`). Each renders via a parametric SQL query.
- `dashboard.py` — composition and formatting for `lh status`.
- `statusline.py` — support for the terminal statusline integration.

Schema + design: [ADR-012 — SQLite monitoring](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/012-sqlite-monitoring.md).

## Scheduler — `scheduler/`

Unified interface over three platform backends:

- `base.py` — `SchedulerJob` dataclass and `SchedulerBackend` protocol (`install`, `uninstall`, `status`).
- `launchd.py` — macOS, writes `.plist` files to `~/Library/LaunchAgents/`.
- `systemd.py` — Linux with systemd user instance, writes `.timer` + `.service` unit files.
- `cron.py` — ubiquitous fallback, edits the user's crontab with lazy-harness markers.
- `manager.py` — `detect_backend` auto-picks based on `platform.system()` + `shutil.which("systemctl")`, overridable via config.

Design: [ADR-013 — Unified scheduler](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/013-scheduler-unified-backends.md).

## Migration engine — `migrate/`

Largest subsystem in the codebase. Four phases across a `state → plan → execute → rollback` pipeline.

```
migrate/
├── detector.py          — scans the system → DetectedState
├── planner.py           — DetectedState → MigrationPlan (ordered list of Steps)
├── executor.py          — runs plan with backup + automatic rollback on failure
├── rollback.py          — serializes and replays the rollback log
├── state.py             — DetectedState, MigrationPlan, StepResult dataclasses
├── gate.py              — dry-run gate, user confirmation layer
└── steps/
    ├── base.py          — Step protocol
    ├── backup.py        — collect targets into <backup_dir>
    ├── config_step.py   — generate config.toml from detected state
    ├── flatten_step.py  — flatten predecessor symlink trees
    └── scripts_step.py  — remove deployed scripts
```

Every step implements `execute(backup_dir, dry_run)` and declares how it undoes itself. The executor writes the rollback log after **every** step (success or failure) and auto-applies it on failure. `--dry-run` is threaded through every step so "what would you do" and "do it" share the same code path.

Design: [ADR-007 — Parallel bootstrap](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/007-parallel-bootstrap-migration.md), [ADR-014 — Migration engine](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/014-migration-engine-rollback.md).

## Selftest — `selftest/`

Parallel in structure to `migrate/`: a tiny runner plus a directory of independent checks.

```
selftest/
├── runner.py            — iterates checks, catches exceptions → synthetic FAIL
├── result.py            — CheckResult (PASS|WARN|FAIL), SelftestReport
└── checks/
    ├── cli_check.py
    ├── config_check.py
    ├── profile_check.py
    ├── hooks_check.py
    ├── scheduler_check.py
    ├── knowledge_check.py
    └── monitoring_check.py
```

Each check returns `list[CheckResult]`. The runner catches exceptions per check so a crash in one does not take down the whole report.

Design: [ADR-017 — Selftest as user-facing health check](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/017-selftest-as-health-check.md).

## CLI — `cli/`

One file per top-level `lh` command, all based on `click`:

- `main.py` — entrypoint + root group, maps to `lh = "lazy_harness.cli.main:cli"` in `pyproject.toml`.
- `init_cmd.py` — interactive wizard delegating to `init/`.
- `migrate_cmd.py` — `lh migrate`, `--dry-run`, `--rollback`.
- `deploy_cmd.py` — `lh deploy`, triggers the three deploy functions.
- `hooks_cmd.py` — `lh hooks list` / `lh hooks run` / dry-run.
- `profile_cmd.py` — `lh profile list/add/remove`.
- `status_cmd.py` — monitoring dashboard.
- `statusline_cmd.py` — terminal statusline support.
- `selftest_cmd.py` — runs the selftest runner and formats the report.
- `doctor_cmd.py` — prerequisite check (uv, python, claude, git).
- `run_cmd.py` — `lh run`, sets `CLAUDE_CONFIG_DIR` and execs `claude`.
- `scheduler_cmd.py` — install / uninstall / status against the scheduler backend.
- `knowledge_cmd.py` — knowledge directory operations (sync, status, grep helpers).

Commands never contain business logic. They parse flags, load config, and delegate to the subsystem modules.

## Data model — three persistent stores

Every piece of state the framework persists lives in one of three places. All three are user-owned and survive `uv tool uninstall`.

| Store | Path | Format | Written by | Read by |
|---|---|---|---|---|
| Config | `~/.config/lazy-harness/config.toml` | TOML (human-edited) | `lh init`, `lh migrate`, `lh profile` | Every subsystem |
| Metrics | `~/.config/lazy-harness/metrics.db` | SQLite | `monitoring/collector.py` | `monitoring/views/*`, `lh status` |
| Knowledge | `<knowledge.path>` (user-configured) | Markdown files | `session-export`, `compound-loop` worker | `context-inject`, QMD, users directly |

There is a fourth semi-persistent store scoped to each deployed profile — `<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/memory/` — which holds `decisions.jsonl`, `failures.jsonl`, `handoff.md`, `pre-compact-summary.md`, and `MEMORY.md`. This is written both by the framework's hooks and by Claude Code itself. It lives in the deployed target dir rather than the source, so version-controlled dotfiles do not accumulate ephemeral session state.

## Memory glue layer — connecting the five layers

The five-layer memory model ([ADR-027](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/027-memory-stack-overview.md)) names the stores; the glue layer ([ADR-030](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/030-memory-stack-glue-layer.md)) makes them work together without depending on the agent remembering its own conventions.

The two key shifts:

- **Deterministic surfacing at SessionStart.** `context_inject` automatically emits a top-3 BM25 query into the QMD vault (using the current branch name) and a `Code structure` summary from the local Graphify graph (or a staleness banner if the graph is older than `git HEAD`). Both fail-soft if the underlying tool is missing. Truncation losses are surfaced as a single `[truncated: ...]` line so the 3000-char budget is tunable from real evidence.
- **Deterministic capture at session close.** The Stop chain runs `session-export → compound-loop → engram-persist`. When `compound-loop`'s LLM-evaluation gates block (short sessions), a deterministic `slim_handoff` fast-path still writes branch + last user prompt + files touched to `handoff.md` so the next session is never blind. The `engram-persist` hook mirrors `decisions.jsonl` / `failures.jsonl` into Engram via cursor-based at-least-once semantics.

What stays prompted (agent judgment): which decisions are worth a manual `mem_save` mid-session, when to deepen a QMD search past the suggester, when to consolidate `MEMORY.md` via `lh memory consolidate`. The harness forces *when* and *where* artifacts are written; *what's worth keeping* remains the agent's call.

## Deployment

Install:

```bash
uv tool install git+https://github.com/lazynet/lazy-harness
lh init     # new install
# or
lh migrate  # from a predecessor setup
```

The binary is `lh`. No compilation, no daemons, no containers. The framework is strictly CLI-driven; everything that looks like "background work" (compound loop worker, scheduler jobs) runs as discrete subprocess invocations.

Language and distribution: [ADR-002 — Python + uv](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/002-python-uv-distribution.md).

## Testing discipline

Tests mirror `src/lazy_harness/` one-to-one. Every module has a test file. Test suite runs in seconds with `uv run pytest`. New code is written red-first per [ADR-015](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/015-strict-tdd-workflow.md); the project rule is "no production code without a failing test that exercised it first".

Two independent verification surfaces exist and are kept strictly separate:

- **`tests/` + pytest** — code correctness, hermetic, developer-facing.
- **`lh selftest` + `selftest/checks/`** — framework health on the user's actual machine, exposed as a user-facing command.

See [ADR-017](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/017-selftest-as-health-check.md) for why these are two separate surfaces.
