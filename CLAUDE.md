# CLAUDE.md — lazy-harness

Instructions for Claude Code and other compatible agents working in this repository. This file is the always-loaded governance surface; details live in the files it points to.

## What this repo is

`lazy-harness` is a cross-platform harnessing framework for AI coding agents, distributed as a Python package (`lh` CLI). Code lives in `src/lazy_harness/`, tests mirror it one-to-one in `tests/`, internal design artifacts in `specs/`, and the public docs site is built from `docs/` with MkDocs Material.

This is a **public repository**. Public surface (README, `docs/` pages, commit messages, PR text) stays generic and professional — no personal names, no references to private predecessor repos. The one exception is `specs/archive/`, which is explicitly historical material.

**`specs/` vs `docs/`:** if a document explains *what* a user of the framework should do or see, it belongs in `docs/`. If it explains *how* we decided to build something, or captures contributor workflow, it belongs in `specs/`. The public site only renders `docs/`.

## Stack (one-liners)

- **Language:** Python 3.11+, strict type hints, no `Any` unless unavoidable.
- **Packaging:** `uv`. Dependencies in `pyproject.toml`. Use `uv sync` / `uv run`.
- **Tests:** `pytest` via `uv run pytest`. Every `src/lazy_harness/` module has a mirrored test file.
- **Lint/format:** `ruff` (config in `pyproject.toml`).
- **Docs site:** MkDocs Material. `uv run --group docs mkdocs build --strict`.
- **Shell scripts:** `set -euo pipefail` always.
- **Containers:** Docker when runtime isolation is needed.

## Non-negotiables

1. **Worktrees for every change.** Any code or docs edit is made in a `.worktrees/<short-name>` worktree on a `<type>/<short-name>` branch, never directly on `main`. Full rules and the `/new-worktree` + `/cleanup-worktree` slash commands: [`specs/workflow/worktrees.md`](specs/workflow/worktrees.md).
2. **Strict TDD.** No production code is written without a failing test that exercises it first. Follow the `superpowers:test-driven-development` skill exactly — invoke it via the `Skill` tool when you start any code change. This rule has no exceptions in this repo, including bug fixes and refactors.
3. **Conventional commits, no AI trailers.** Format: `type: short description` (e.g. `fix: handle missing profile dir`). Do **not** add `Co-Authored-By` or any AI-attribution trailers. Do **not** skip hooks with `--no-verify`. Create new commits instead of amending published ones.
4. **Pre-commit verification is all three checks.** Run `/tdd-check` before every commit: `uv run pytest`, `uv run ruff check src tests`, and `uv run --group docs mkdocs build --strict` must all pass with pristine output.
5. **Versions are owned by release-please.** Never hand-bump `pyproject.toml` or `src/lazy_harness/__init__.py`, never tag `vX.Y.Z` manually. Mechanism and commit-type rules: [`specs/workflow/release-flow.md`](specs/workflow/release-flow.md).

## What NOT to do

- Do not write production code without a failing test first. See non-negotiable #2.
- Do not generate READMEs, standalone documentation pages, or obvious code comments unless explicitly asked. Tests are always in scope under TDD and exempt from this rule.
- Do not refactor code that was not part of the task. If you spot something worth improving, mention it; do not touch it.
- Do not introduce abstractions for hypothetical future needs. Three similar lines beats a premature abstraction.
- Do not reintroduce references to the project's pre-rename name or any individual user's name into public surface: `README.md`, `docs/index.md`, `docs/why/*`, `docs/getting-started/*`, `docs/reference/*`, `docs/architecture/overview.md`, `mkdocs.yml`. Only `specs/archive/**` is allowed to carry that history.
- Do not edit files in `specs/archive/**` to "fix" historical references, stale paths, or outdated nomenclature. That tree is frozen on purpose. Moving files as part of a wider restructure is fine; editing their content is not.
- Do not commit secrets, credentials, or personal identifying information.

## Where things live

High-level map: [`specs/workflow/layout.md`](specs/workflow/layout.md). Short form:

- `src/lazy_harness/<area>/` → code, one file per `lh` subcommand in `cli/`
- `tests/` → mirrors `src/lazy_harness/` one-to-one
- `docs/` → public MkDocs site
- `specs/adrs/` → active decision records (see [`specs/adrs/README.md`](specs/adrs/README.md) for the index and status vocabulary)
- `specs/designs/` → long-form design specs
- `specs/workflow/` → internal contributor workflow (worktrees, release flow, layout)
- `specs/archive/` → frozen historical material, do not edit

## Slash commands available in this repo

- `/new-worktree <type>/<short-name>` — create a worktree and branch with correct naming. [`.claude/commands/new-worktree.md`](.claude/commands/new-worktree.md)
- `/cleanup-worktree <short-name>` — remove a merged worktree and its branch after verifying it was merged. [`.claude/commands/cleanup-worktree.md`](.claude/commands/cleanup-worktree.md)
- `/tdd-check` — run pytest + ruff + mkdocs build as the pre-commit gate. [`.claude/commands/tdd-check.md`](.claude/commands/tdd-check.md)
