# CLAUDE.md — lazy-harness

Instructions for Claude Code (and other compatible agents) when working in this repository.

## What this repo is

`lazy-harness` is a cross-platform harnessing framework for AI coding agents, distributed as a Python package (`lh` CLI). The code lives in `src/lazy_harness/`, tests mirror it one-to-one in `tests/`, and the public docs site is built from `docs/` with MkDocs Material and deployed to GitHub Pages on every push to `main`.

This is a **public repository**. Public surface (README, `docs/` user-facing pages, commit messages, issue/PR text) should stay generic and professional — no personal names, no references to private predecessor repos. The `docs/history/` and `docs/architecture/decisions/legacy/` trees are explicitly archived material and are allowed to reference the project's pre-rename history; everything else should not.

## Stack

- **Language:** Python 3.11+ with strict type hints. No `Any` unless unavoidable.
- **Package manager:** `uv`. Dependencies live in `pyproject.toml`. Use `uv sync` / `uv run`.
- **Tests:** `pytest` via `uv run pytest`. Every module under `src/lazy_harness/` has a corresponding test file under `tests/`.
- **Lint/format:** `ruff` (config in `pyproject.toml`).
- **Docs:** MkDocs Material. `uv run mkdocs serve` for local preview, `uv run mkdocs build --strict` to verify builds cleanly.
- **Shell scripts** (when unavoidable): `set -euo pipefail`.
- **Containers:** prefer Docker when runtime isolation is needed.

## Workflow rules

### Worktrees for all changes

**Any code or docs change must be made in a git worktree, not directly on `main`.** This is non-negotiable for this repo.

- Worktrees live in `.worktrees/` (git-ignored, project-local).
- Create with: `git worktree add .worktrees/<short-name> -b <branch>`.
- Branch naming: `feat/*`, `fix/*`, `docs/*`, `chore/*`, `refactor/*`.
- Work inside the worktree, commit there, then open a PR from that branch.
- After the branch is merged, remove the worktree: `git worktree remove .worktrees/<short-name>`.
- Never create a worktree in a directory that isn't `.gitignore`d.

### Commits

- Trunk-based: small, frequent commits. Short-lived branches.
- Conventional commits: `type: short description` (e.g. `fix: handle missing profile dir`, `docs: clarify migrate --rollback`).
- Do **not** add `Co-Authored-By` or any AI-attribution trailers in commit messages.
- Do not use `--no-verify` or skip hooks unless explicitly asked.
- Create new commits instead of amending published ones.

### Tests before claiming done

Run the relevant tests before reporting a task complete. For framework changes:

```bash
uv run pytest
uv run ruff check src tests
```

For docs changes:

```bash
uv run mkdocs build --strict
```

Type checking and tests verify code correctness, not feature correctness. If a change is user-visible (CLI output, hook behavior, config parsing), exercise the feature end-to-end before calling it done.

## What NOT to do

- Do not generate tests, READMEs, or documentation unless explicitly asked. Do not add obvious code comments.
- Do not refactor code that wasn't part of the task. If you spot something worth improving, mention it — don't touch it.
- Do not introduce abstractions for hypothetical future needs. Three similar lines beats a premature abstraction.
- Do not reintroduce references to the project's pre-rename name or any individual user's name into public-facing docs (`README.md`, `docs/index.md`, `docs/why/*`, `docs/getting-started/*`, `docs/reference/*`, `docs/architecture/overview.md`, `mkdocs.yml`). `docs/history/**` and `docs/architecture/decisions/legacy/**` are the only places where historical references belong, and they are explicitly archived.
- Do not edit files in `docs/history/**` or `docs/architecture/decisions/legacy/**` to "fix" their historical references — those trees are preserved as-is on purpose.
- Do not commit secrets, credentials, or personal identifying information of any user.

## Layout cheatsheet

```
src/lazy_harness/
├── agents/          # Agent adapters (claude_code today, others planned)
├── cli/             # Click command groups — one file per `lh <command>`
├── core/            # Config, paths, profiles, envrc — foundational
├── deploy/          # Symlink and deploy engine
├── hooks/           # Hook engine + built-in hooks
├── init/            # Interactive `lh init` wizard
├── knowledge/       # Knowledge dir, QMD index, compound loop
└── ...
tests/               # Mirrors src/lazy_harness/ one-to-one
docs/                # MkDocs site source (public)
├── why/             # Problem, philosophy, memory model
├── getting-started/ # Install, first run, migrating
├── reference/       # CLI, config
├── architecture/    # Overview, ADRs
└── history/         # ARCHIVED — do not edit for cleanup
```

## Release flow

Version is tracked in `pyproject.toml`. Release = bump version, commit, tag, push:

```bash
git commit -am "chore: bump version to X.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z — short note"
git push origin main && git push origin vX.Y.Z
```

CI rebuilds and redeploys the docs site on every push to `main`.
