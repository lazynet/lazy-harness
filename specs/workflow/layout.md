# Repository layout

Map of where things live. The short version is in `CLAUDE.md`; this file is the expanded "why each tree exists" reference.

```
src/lazy_harness/
├── agents/          # Agent adapters (claude_code today, others planned)
├── cli/             # Click command groups — one file per `lh <command>`
├── core/            # Config, paths, profiles, envrc — foundational
├── deploy/          # Symlink and deploy engine
├── hooks/           # Hook engine + built-in hooks
├── init/            # Interactive `lh init` wizard
├── knowledge/       # Knowledge dir, QMD index, compound loop
├── metrics/         # Metrics sinks (local sqlite + optional remote)
├── migrate/         # Detect → plan → execute → rollback engine
├── monitoring/      # SQLite monitoring store + view modules
├── scheduler/       # launchd / systemd / cron backends
└── selftest/        # User-facing `lh selftest` health check

tests/               # Mirrors src/lazy_harness/ one-to-one
                     # Every module has a corresponding test file.

docs/                # MkDocs site source — PUBLIC, published to GitHub Pages
├── why/             # Problem statement, philosophy, memory model
├── getting-started/ # Install, first run, migrating
├── reference/       # CLI reference, config reference
├── how/             # How-to guides for users of the framework
└── architecture/    # Narrative overview only — ADRs live in specs/adrs/

specs/               # Internal design artifacts — NOT published
├── adrs/            # Active Architecture Decision Records
├── designs/         # Long-form design specs from brainstorming
├── workflow/        # Internal contributor workflow (this directory)
└── archive/         # ARCHIVED — do not edit for cleanup
    ├── adrs-legacy/ # Predecessor project's ADRs
    └── history/     # Early plans, specs, workflows, genesis notes
```

## Decision helper — where does this thing go?

- **New CLI command** → `src/lazy_harness/cli/<name>_cmd.py`, tests in `tests/unit/cli/test_<name>_cmd.py`, reference entry in `docs/reference/cli.md`.
- **New extension point / plugin type** → new directory under `src/lazy_harness/`, public overview in `docs/architecture/overview.md`, decision record in `specs/adrs/`.
- **New ADR** → `specs/adrs/NNN-kebab-title.md`, add row to `specs/adrs/README.md` with Status column.
- **New user-facing guide** → `docs/how/<topic>.md`, linked from `mkdocs.yml`.
- **New contributor-only doc** → `specs/workflow/<topic>.md` (this directory) or `specs/designs/<date>-<topic>.md` for in-progress designs.
- **Historical context you want to preserve but not edit** → leave in `specs/archive/` and do not touch.

## What each tree is NOT for

- `src/lazy_harness/` is not a place for scripts, experiments, or one-off tooling. Those go under a scratch directory or a separate branch and do not get shipped.
- `tests/` is not a place for sample fixtures that are also shipped code. Real test data lives alongside the tests.
- `docs/` is not for internal reasoning. If it reveals how a decision was made or mentions implementation alternatives, it belongs in `specs/` instead.
- `specs/archive/` is not a cleanup target. It is frozen on purpose. Moving archive files as part of a wider restructure is fine; editing their content is not.
