# Architecture overview

A map of the codebase and the module boundaries.

## Top-level layout

```
lazy-harness/
├── src/lazy_harness/
│   ├── cli/             — click subcommands (one file per command)
│   ├── core/            — config, paths, profiles, envrc
│   ├── agents/          — agent adapter protocol + claude-code adapter
│   ├── hooks/           — hook engine, builtins, user hook loader
│   ├── monitoring/      — SQLite ingest, views
│   ├── knowledge/       — session export, QMD wrapper
│   ├── scheduler/       — launchd, systemd, cron backends
│   ├── migrate/         — detector, planner, executor, rollback, steps/
│   ├── init/            — wizard
│   ├── selftest/        — runner, checks/
│   └── deploy/          — symlink engine
├── tests/               — pytest, mirrors src structure
├── templates/           — file templates (profile scaffolds, etc.)
└── docs/                — this site
```

## Key abstractions

### `Config` and `paths`

`core/config.py` defines the typed config model, loaded from `config.toml` via `tomllib`. `core/paths.py` resolves installation directories with explicit env var > XDG > platform defaults priority. Everything downstream reads from these two modules — there is no other path resolution in the codebase.

### Agent adapter

`agents/base.py` defines a protocol that abstracts over agent-specific details: where the agent reads settings from, what format hooks use, how the agent reports session state. Today the only implementation is `agents/claude_code.py`. Adding support for another agent means implementing this protocol and registering it in `agents/registry.py`.

### Hook engine

`hooks/` is a registry + dispatcher. Built-in hooks live at `hooks/builtins/`. User hooks declared in `config.toml` are resolved via `hooks/loader.py`. The engine speaks JSON over stdin/stdout — a hook is any executable that reads a JSON event and optionally prints JSON modifications.

### Migration engine

`migrate/` is the biggest subsystem. Its shape:

```
migrate/
├── detector.py          — scans system → DetectedState
├── planner.py           — DetectedState → MigrationPlan
├── executor.py          — runs plan with backup + rollback
├── rollback.py          — rollback registry
├── state.py             — dataclasses
├── errors.py            — MigrateError subclasses
└── steps/               — one file per step type
    ├── base.py          — Step protocol
    ├── backup.py
    ├── config_step.py
    ├── profiles_step.py
    ├── hooks_step.py
    ├── ... (etc.)
```

Each step declares a forward operation and its inverse. The executor runs them in order, appending rollback entries as it goes. If any step fails, automatic rollback runs immediately.

### Selftest

`selftest/` is parallel in structure to migrate: a runner orchestrates check groups, each check group lives in `checks/`. Every check returns a `CheckResult` with status, message, and optional fix hint.

## Deployment model

`lazy-harness` is installed via `uv tool install`. The binary is `lh`, declared in `pyproject.toml` as `[project.scripts] lh = "lazy_harness.cli.main:cli"`. No compilation, no containers, no daemons.

Profiles are NOT bundled with the framework. They live at `~/.config/lazy-harness/profiles/<name>/`, owned by the user and versioned with their dotfiles. `lh profile deploy` creates symlinks from `~/.config/lazy-harness/profiles/` into `~/.claude-<name>/` so Claude Code reads them.

## Data model

Three persistent stores:

1. **Config** — `~/.config/lazy-harness/config.toml`, human-edited TOML.
2. **Metrics** — `~/.config/lazy-harness/metrics.db`, SQLite, written by the ingest pipeline, read by `lh status`.
3. **Knowledge** — user-configured directory, plain markdown files. Optionally indexed by QMD.

All three are user-owned and survive `uv tool uninstall`.

## Testing

`tests/` mirrors `src/lazy_harness/` one-to-one. Every module has a test file. Tests use pytest, run with `uv run pytest`. The framework has ~194 tests at v0.3.6. Coverage is enforced informally (every new feature adds tests; no coverage threshold tooling).

## Design decisions

For the "why" behind specific choices, see the [framework ADRs](adrs/001-hybrid-architecture.md) and the [legacy ADRs](decisions/legacy/README.md) migrated from `lazy-claudecode`.
