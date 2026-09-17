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
├── knowledge/       # session export, QMD wrapper, compound loop, graphify wrapper
├── memory/          # engram wrapper (ADR-022 episodic backend)
├── llm/             # inference backends + role routing (ADR-033, ADR-039)
├── monitoring/      # SQLite ingest, views, dashboard, engram-persist health
├── scheduler/       # launchd, systemd, cron backends + manager
├── migrate/         # detector, planner, executor, rollback, steps/
├── init/            # interactive `lh init` wizard
├── selftest/        # runner, checks/
├── deploy/          # symlink engine, agent config generation, MCP wiring
├── wizards/         # `lh config <feature> --init` flows (ADR-026)
├── plugins/         # extension-point registry (metrics sinks, future surfaces)
└── features.py      # `lh doctor` Features section helper (ADR-025)
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
- `supported_hooks()` + `hook_events()` — what events exist, under what native name, and which permission verdicts the agent actually honors on each.
- `parse_hook_input()` / `format_hook_output()` — translate the agent's native hook payload into the canonical event, and a decision back into the channels that agent reads.

Writing the agent's config files is a separate, optional protocol, `ConfigPlanner`: `config_targets()` names the files an adapter may touch and `plan_config()` returns the complete set of writes. It is separate because a single `dict` return cannot express "N files in two formats" — Claude Code wants `settings.json` plus `.claude.json`, Codex a `hooks.json`.

`agents/claude_code.py` is the reference implementation. `agents/registry.py` maps `config.toml`'s `[agent].type` value to an adapter class. Adding a new agent = one file + one registry entry, with no other code in the framework touching agent-specific concerns.

Design: [ADR-004 — Agent adapter pattern](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/004-agent-adapter-pattern.md).

## Hook engine — `hooks/`

`hooks/loader.py` resolves hook names to executable paths. Built-in hooks are looked up first (`_BUILTIN_HOOKS` dict under `hooks/builtins/`); user hooks fall through to `~/.config/lazy-harness/hooks/<name>.py`. `resolve_hooks_for_event(cfg, event)` returns the ordered list of resolved hooks for a given event name from config.

`hooks/engine.py` provides `execute_hook` + `run_hooks_for_event` — used by `lh hooks run` and the test suite. At runtime, the agent itself spawns hooks; the framework does not orchestrate them. The engine is for programmatic invocation only.

Built-in hooks live under `hooks/builtins/`, one module per hook. Which of them ship **on** by default is not restated here — it is derived from `plugins/builtins.py`, and `docs/how/hooks.md` documents every one of them with a section apiece, held to the registry by `tests/docs/test_hooks_doc_coherence.py` in both directions. The four load-bearing ones:

- `context_inject.py` — SessionStart, composes and injects context.
- `compound_loop.py` — Stop producer, enqueues async worker. See [how hooks work](../how/hooks.md#compound-loop-runs-on-stop).
- `session_export.py` — Stop, exports session to the knowledge store.
- `pre_compact.py` — PreCompact, preserves working state before compaction.

Design: [ADR-006](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/006-hooks-subprocess-json.md). End-to-end mechanics: [how hooks work](../how/hooks.md).

## Knowledge layer — `knowledge/`

- `marker.py` — reads, writes and validates the store's `knowledge.toml`; resolves the store root.
- `directory.py` — store layout: creates the store and resolves paths from its marker.
- `git_push.py` — one commit/rebase/push cycle over the store, under `flock`.
- `session_export.py` — JSONL → markdown export with classification and atomic writes.
- `compound_loop.py` — pure functions for the compound loop (parse, filter, build prompt, parse response, persist). Flat module so each step is independently testable.
- `compound_loop_worker.py` — runnable via `python -m`, drains the file-based queue under `fcntl.flock`.
- `qmd.py` — optional QMD CLI wrapper, guarded by `shutil.which("qmd")`.
- `graphify.py` — optional Graphify CLI wrapper and version pin.
- `engram_persist.py` — `EngramPersister`, the cursor-based JSONL → Engram mirror.
- `context_gen.py` — shared helpers for context composition.

Detailed flow: [how the memory compound loop works](../how/memory-compound.md) and [how the knowledge pipeline works](../how/knowledge-pipeline.md).

Design decisions: [ADR-008](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/008-compound-loop-async-worker.md), [ADR-010](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/010-pre-compact-preservation.md), [ADR-011](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/011-session-export-and-classification.md), [ADR-016](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/016-knowledge-dir-qmd-optional.md).

## Deploy engine — `deploy/`

Every `lh deploy` snapshots first. `deploy/snapshot.py` writes a manifest of the artifacts the three functions below are about to touch — one entry per destination, carrying its absolute path, its kind (`file`, `symlink`, or `absent` for something the deploy is about to create), and for a file a content path unique per destination rather than per basename, because `~/.claude-lazy/settings.json` and `~/.claude-flex/settings.json` share one. `core/backups.py` decides where it lands: `~/.config/lazy-harness/backups/deploy/<ts>/`, pruned to the newest ten, in a namespace `lh migrate --rollback` cannot reach and a deploy's prune cannot delete from. `lh deploy --rollback` replays the newest through `migrate/rollback.py`.

`deploy/engine.py` has three top-level functions called by `lh deploy`:

1. **`deploy_profiles(cfg)`** — for each profile, symlink every item from `~/.config/lazy-harness/profiles/<name>/*` into `<profile.config_dir>/`. Per-file symlinks (not whole-directory), idempotent.
2. **`deploy_config(cfg)`** — for each profile, run the config cycle: ask the adapter for `config_targets()`, read the ones on disk, call `plan_config()` once with the resolved hook entries and the probed MCP servers, and apply the `WriteOp`s that come back. Merging is the adapter's — parsing a native config format never was agent-neutral — so the engine writes the returned text verbatim, deletes what the plan retires, writes a `.bak` when the plan reports a repair, and prints the preserved/dropped/repaired diagnostics. An adapter that cannot plan its config is refused before the first write, never discovered mid-deploy.
3. **`deploy_claude_symlink(cfg)`** — create `~/.claude → <default profile config_dir>`.

`deploy_hooks(cfg)` and `deploy_mcp_servers(cfg)` remain as narrowings of `deploy_config` that plan with one half of the inputs blanked out. Nothing in the CLI calls them; they exist for tests that drive one document at a time.

`deploy/symlinks.py` implements `ensure_symlink`, which returns `"exists"` when the target is already a symlink to the correct source and `"created"` otherwise. It does **not** refuse: a symlink pointing elsewhere is unlinked and replaced, and a real file or directory at the target is renamed to `<name>.bak` before the link is written. The `.bak` is a single slot, not a chain — a second deploy over a second real file overwrites the first backup.

Design: [ADR-009 — Profile symlink deploy](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/009-profile-symlink-deploy.md), [ADR-024 — MCP server orchestration](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/024-mcp-server-orchestration.md). Mechanics: [how profiles and deploy work](../how/profiles-and-deploy.md).

## Monitoring — `monitoring/`

Local SQLite store populated by parsing session JSONLs:

- `db.py` — the schema every reader and writer shares: `session_stats` with `UNIQUE(session, model)` for idempotent re-ingestion plus an index on `date`, `session_attribution` and `ingest_meta` keyed by session, `sink_outbox` for undelivered events, and two append-only event logs — `loop_events` (one row per graded session or fired hook) and `launches` (one row per agent launch `lh run` or `lh exec` actually started). Every table is created with `CREATE TABLE IF NOT EXISTS` on each open, so a store written by an older `lh` picks up a new table the first time a newer one touches it.
- `collector.py` — walks `<CLAUDE_CONFIG_DIR>/projects/**/*.jsonl`, extracts per-session token counts (input, output, cache_read, cache_create), computes cost against `[monitoring.pricing]`, and does `INSERT OR IGNORE` into the DB. Still the path `lh exec` prices a session through (ADR-053).
- `ingest.py` — `lh metrics ingest`'s path: `ingest_profile` resolves the profile's adapter and reads it through `isinstance(agent, TranscriptReader)` rather than a hardcoded dialect, so any agent whose adapter implements the Protocol is metered the same way; one that does not is skipped and named by `lh doctor` instead of scanned as if it were Claude Code (ADR-051, ADR-053). `ingest_all` stamps `agent` and the profile's `billing_model` on every row.
- `pricing.py` — cost calculation from the pricing dict.
- `views/` — one file per viewing angle (`overview`, `projects`, `profiles`, `sessions`, `tokens`, `cron`, `hooks`, `memory`, `queue`). Each renders via a parametric SQL query.
- `dashboard.py` — composition and formatting for `lh status`.
- `statusline.py` — support for the terminal statusline integration.

Schema + design: [ADR-012 — SQLite monitoring](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/012-sqlite-monitoring.md).

## Scheduler — `scheduler/`

Unified interface over three platform backends:

- `base.py` — `SchedulerJob` dataclass and `SchedulerBackend` protocol (`install`, `uninstall`, `status`).
- `launchd.py` — macOS, writes `.plist` files to `~/Library/LaunchAgents/`.
- `systemd.py` — Linux with a systemd user instance. Writes `.timer` + `.service` units under `$XDG_CONFIG_HOME/systemd/user/`, enables them with `systemctl --user`, and warns when lingering is off, since user timers stop at logout without it.
- `cron.py` — the ubiquitous floor. Writes a `# BEGIN lazy-harness` / `# END lazy-harness` block into the user's crontab, so uninstall removes exactly what install wrote and never touches their own entries.
- `manager.py` — `detect_backend` auto-picks based on `platform.system()` + `shutil.which("systemctl")`, overridable via config.

Design: [ADR-013 — Unified scheduler](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/013-scheduler-unified-backends.md).

## Migration engine — `migrate/`

Largest subsystem in the codebase. Four phases across a `state → plan → execute → rollback` pipeline.

```
migrate/
├── detector.py          — scans the system → DetectedState
├── planner.py           — DetectedState → MigrationPlan (ordered list of Steps)
├── executor.py          — runs plan with backup + automatic rollback on failure
├── rollback.py          — serializes and replays the rollback log, in two
│                          formats: a JSON list is a migration's, a dict with
│                          `format: manifest` is a deploy snapshot's
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
    ├── monitoring_check.py
    └── loop_events_check.py
```

Each check returns `list[CheckResult]`. The runner catches exceptions per check so a crash in one does not take down the whole report.

Design: [ADR-017 — Selftest as user-facing health check](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/017-selftest-as-health-check.md).

## CLI — `cli/`

One file per top-level `lh` command, all based on `click`:

- `main.py` — entrypoint + root group, maps to `lh = "lazy_harness.cli.main:cli"` in `pyproject.toml`.
- `init_cmd.py` — interactive wizard delegating to `init/`.
- `migrate_cmd.py` — `lh migrate`, `--dry-run`, `--rollback`.
- `deploy_cmd.py` — `lh deploy`, `--profile`, `--snapshot`, `--rollback`; triggers the three deploy functions.
- `hooks_cmd.py` — `lh hooks list` / `lh hooks run` / dry-run.
- `profile_cmd.py` — `lh profile list/add/remove`.
- `status_cmd.py` — monitoring dashboard.
- `statusline_cmd.py` — terminal statusline support.
- `selftest_cmd.py` — runs the selftest runner and formats the report.
- `doctor_cmd.py` — prerequisite check (uv, python, claude, git).
- `run_cmd.py` — `lh run`, sets `CLAUDE_CONFIG_DIR` and execs `claude`.
- `scheduler_cmd.py` — install / uninstall / status against the scheduler backend.
- `knowledge_cmd.py` — knowledge store operations (init, path, push, sync, status).
- `config_cmd.py` — `lh config <feature> --init` wizards (`knowledge`, `memory`) plus `lh config migrate-knowledge`, delegating to `wizards/`.
- `memory_cmd.py` — memory-stack diagnostics (status, consolidate, decay, reconcile, proposals, rightsize, legacy-check, migrate).
- `metrics_cmd.py` — `lh metrics ingest` / `drain` / `status` / `loops` / `record-verify`.
- `exec_cmd.py` — `lh exec`, the role-routed inference entrypoint (ADR-038, ADR-039).

Commands never contain business logic. They parse flags, load config, and delegate to the subsystem modules.

## Data model — three persistent stores

Every piece of state the framework persists lives in one of three places. All three are user-owned and survive `uv tool uninstall`.

| Store | Path | Format | Written by | Read by |
|---|---|---|---|---|
| Config | `~/.config/lazy-harness/config.toml` | TOML (human-edited) | `lh init`, `lh migrate`, `lh profile` | Every subsystem |
| Metrics | `~/.local/share/lazy-harness/metrics.db` (`data_dir()`; `[monitoring].db` overrides) | SQLite | `monitoring/ingest.py`, `monitoring/sinks/*` | `monitoring/views/*`, `lh status`, `lh metrics` |
| Knowledge | knowledge store root (env, `[knowledge].root`, or default) | Markdown files, layout declared by `knowledge.toml` | `session-export`, `compound-loop` worker | `context-inject`, QMD, users directly |

Distilled per-project memory — `MEMORY.md`, `decisions.jsonl`, `failures.jsonl`, `grades.jsonl`, `handoff.md`, `pre-compact-summary.md`, `insights/` — is not a fourth store. It lives **inside** the knowledge store, under the area its `knowledge.toml` marker declares (`memory` by default), keyed by the project's own identity rather than by the path of the checkout:

```
<store root>/memory/<host>/<owner>/<repo>/
```

`core/project_identity.py` derives that key from the repository's normalised git remote, so the same repo on two machines resolves to one directory and a session run from a linked worktree writes to the same place as one run from the main checkout. `core/memory_store.py` is the only module that builds the path; every hook and CLI reader goes through `hooks/builtins/_shared.py:memory_dir`.

Two cases fall back to the legacy location, `<CLAUDE_CONFIG_DIR>/projects/<encoded-cwd>/memory/`: no usable knowledge store, and a checkout with no git remote (the key would be `local/<name>`, which two unrelated directories on two machines would collide under in a store that gets pushed). `lh memory legacy-check` lists what is still sitting there and `lh memory migrate` moves it.

Claude Code's own write-side state — session JSONLs under `projects/`, `logs/` — stays in the deployed target dir, which is why version-controlled dotfiles never accumulate ephemeral session state.

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
