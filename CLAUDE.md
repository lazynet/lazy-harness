# CLAUDE.md — lazy-harness

Instructions for Claude Code (and other compatible agents) when working in this repository.

## What this repo is

`lazy-harness` is a cross-platform harnessing framework for AI coding agents, distributed as a Python package (`lh` CLI). The code lives in `src/lazy_harness/`, tests mirror it one-to-one in `tests/`, internal design artifacts (ADRs, specs) live in `specs/`, and the public docs site is built from `docs/` with MkDocs Material and deployed to GitHub Pages on every push to `main`.

This is a **public repository**. Public surface (README, `docs/` user-facing pages, commit messages, issue/PR text) should stay generic and professional — no personal names, no references to private predecessor repos. The `specs/archive/` tree is explicitly archived material and is allowed to reference the project's pre-rename history; everything else should not.

### `specs/` vs `docs/`

- **`docs/`** — public, user-facing documentation. Published to GitHub Pages via MkDocs. Covers install, use, how things work, and narrative architecture overview.
- **`specs/`** — internal design artifacts. Tracked in git but **not** published. Contains three subtrees:
  - `specs/adrs/` — active ADRs (short decision records).
  - `specs/designs/` — long-form design specs produced during brainstorming.
  - `specs/archive/` — frozen historical material (legacy ADRs, early plans/specs, genesis notes). Preserved as-is for provenance.

If a document explains *what* a user of the framework should do or see, it belongs in `docs/`. If it explains *how* we decided to build something, or captures an in-progress design, it belongs in `specs/`.

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

### Strict TDD — no production code without a failing test first

**This repository follows strict Test-Driven Development. It is non-negotiable for any code change — new features, bug fixes, and refactors alike.**

The iron law: **no production code is written without a failing test that exercises it first.** If you write implementation code before the test, delete it and start over. "Keep it as reference" counts as starting with implementation — delete means delete.

The Red → Green → Refactor cycle, applied every time:

1. **RED — write one failing test.** One behavior, one test. Clear name that describes the behavior, not the implementation. Real code over mocks unless a dependency genuinely can't be exercised.
2. **Verify RED — run the test and watch it fail.** Mandatory. Confirm the failure message is the one you expected and that it fails because the feature is missing, not because of a typo or import error. A test that passes immediately proves nothing.
3. **GREEN — write the minimal code to make the test pass.** No extra features, no speculative parameters, no "while I'm here" refactors. Just enough to flip red to green.
4. **Verify GREEN — run the test and the rest of the suite.** Confirm the new test passes, nothing else broke, and the output is pristine (no warnings, no deprecation noise).
5. **REFACTOR — clean up while staying green.** Remove duplication, improve names, extract helpers. Do not add behavior in this step. Re-run tests after each change.
6. **Repeat** for the next behavior.

Bug fixes follow the same cycle: reproduce the bug as a failing test first, then fix. This guarantees the fix is real and the regression is guarded.

Commands for this repo:

```bash
uv run pytest tests/path/to/test_file.py::test_name   # Watch one test fail / pass
uv run pytest                                          # Full suite before committing
uv run ruff check src tests
uv run mkdocs build --strict                           # For docs changes
```

Before marking any code task complete, confirm:

- [ ] Every new function or branch has at least one test that failed before its implementation existed.
- [ ] You ran each test and watched it fail for the expected reason.
- [ ] The minimal code to pass each test is the only production code added.
- [ ] The full suite (`uv run pytest`) is green with pristine output.
- [ ] Edge cases and error paths are covered, not just the happy path.

If you can't check every box, you skipped TDD — start over.

User-visible changes (CLI output, hook behavior, config parsing) additionally need end-to-end exercise of the feature, because tests verify code correctness, not feature correctness.

## What NOT to do

- Do not write production code without a failing test first. See the TDD section above — this rule has no exceptions in this repo.
- Do not generate READMEs or standalone documentation pages unless explicitly asked. (Tests are always in scope under TDD; this exclusion does not apply to them.) Do not add obvious code comments.
- Do not refactor code that wasn't part of the task. If you spot something worth improving, mention it — don't touch it.
- Do not introduce abstractions for hypothetical future needs. Three similar lines beats a premature abstraction.
- Do not reintroduce references to the project's pre-rename name or any individual user's name into public-facing docs (`README.md`, `docs/index.md`, `docs/why/*`, `docs/getting-started/*`, `docs/reference/*`, `docs/architecture/overview.md`, `mkdocs.yml`). `specs/archive/**` is the only place where historical references belong, and it is explicitly archived.
- Do not edit files in `specs/archive/**` to "fix" their historical references, stale paths, or outdated nomenclature — that tree is preserved as-is on purpose. Moving files as part of a wider restructure is fine; editing their content is not.
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
└── architecture/    # Overview only — ADRs live in specs/adrs/
specs/               # Internal design artifacts (NOT published)
├── adrs/            # Active Architecture Decision Records
├── designs/         # Long-form design specs from brainstorming
└── archive/         # ARCHIVED — do not edit for cleanup
    ├── adrs-legacy/ # Predecessor project's ADRs
    └── history/     # Early plans, specs, workflows, genesis notes
```

## Release flow

Versions are managed by **release-please** (`.github/workflows/release-please.yml`). Do not bump `pyproject.toml` or `src/lazy_harness/__init__.py` by hand, and do not create `vX.Y.Z` tags manually.

On every push to `main`, release-please scans commits since the last release, decides the next version from conventional-commit types (`feat:` → minor, `fix:` → patch, `BREAKING CHANGE:` in the footer → major), and opens a PR titled `chore(main): release X.Y.Z` that contains the version bump in both files, a `CHANGELOG.md` entry grouped by section, and nothing else. **Merging that PR is the release** — release-please then creates the `vX.Y.Z` tag and a GitHub Release automatically.

What this means in practice:

- Use conventional-commit prefixes rigorously. A `fix:` in a merged PR triggers a patch bump; a `feat:` triggers a minor bump. `chore:`, `ci:`, `test:` are hidden from the changelog but still allowed.
- `BREAKING CHANGE:` in the commit body (or a `!` after the type, e.g. `feat!: …`) triggers a major bump. Use sparingly.
- If you need to edit the release PR (fix a changelog typo, add missing context), edit it in place — release-please re-opens rather than duplicates.
- The docs site still redeploys on every push to `main` via `.github/workflows/docs.yml`. A release merge is just another push for that workflow.

Both `pyproject.toml` (`[project].version`) and `src/lazy_harness/__init__.py` (`__version__` line with the `x-release-please-version` marker) are kept in sync by the tool. `tests/unit/test_version.py` guards the invariant that the two files never drift.
