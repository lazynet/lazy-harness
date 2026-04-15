# Contributing to lazy-harness

Thanks for looking at the project. This file is a short pointer to the places that matter — the full contributor contract lives in `CLAUDE.md` and `specs/workflow/`.

## Before you start

`lazy-harness` is a single-maintainer project with a strict discipline. Two things are worth knowing up front:

- **Strict TDD is non-negotiable.** No production code lands without a failing test written first. See `CLAUDE.md` non-negotiable #2 for the exact rule, and [`specs/workflow/README.md`](specs/workflow/README.md) for the pointer to the `superpowers:test-driven-development` skill that codifies the workflow.
- **Every change is made in a git worktree, not on `main`.** See [`specs/workflow/worktrees.md`](specs/workflow/worktrees.md) for the full rules. The repo provides a `/new-worktree` slash command that scaffolds the worktree with correct naming.

If either of those is a dealbreaker for your workflow, `lazy-harness` is probably not the right project to contribute to — no judgement, but it saves both of us time to know it early.

## Development setup

```bash
git clone https://github.com/lazynet/lazy-harness.git
cd lazy-harness
uv sync
uv run pytest         # should be green
uv run ruff check src tests
```

If any of those fail on a clean clone, that is a bug in the repo itself — please open an issue.

## Making a change

1. Create a worktree and a branch with a conventional-commit type prefix:
   ```bash
   git worktree add .worktrees/<short-name> -b <type>/<short-name>
   ```
   Where `<type>` is one of `feat`, `fix`, `docs`, `chore`, `refactor`. Full rules in [`specs/workflow/worktrees.md`](specs/workflow/worktrees.md).
2. Follow strict TDD: write a failing test, watch it fail, write the minimal code to pass, refactor. Repeat.
3. Before committing, run the full pre-commit gate — either manually or via the `/tdd-check` slash command:
   ```bash
   uv run pytest
   uv run ruff check src tests
   uv run --group docs mkdocs build --strict
   ```
   All three must pass with pristine output.
4. Use [conventional commits](https://www.conventionalcommits.org/) for the commit message. Release-please uses them to drive version bumps — see [`specs/workflow/release-flow.md`](specs/workflow/release-flow.md) for what each type means.
5. Open a PR from your branch. The PR template will ask you for a Summary, a Why, and a Test plan.

## What to file an issue about

- **Bugs:** use the bug-report template. Include a minimal reproduction if possible.
- **Feature requests:** use the feature-request template. Expect the request to be weighed against the items on the public [`docs/roadmap.md`](docs/roadmap.md) — features outside a committed theme may take a while to land, or land in a different form.
- **Questions about usage:** open a discussion-style issue rather than a bug report. The `docs/` site covers the happy path.

## What not to do

These are the same `What NOT to do` rules from `CLAUDE.md`, reproduced here so external contributors see them without having to read the agent-facing file:

- Do not write production code without a failing test first.
- Do not refactor code that was not part of your task. Mention improvements in the PR description; do not touch them.
- Do not introduce abstractions for hypothetical future needs.
- Do not edit files in `specs/archive/**`. That tree is intentionally frozen.
- Do not hand-bump `pyproject.toml` or `src/lazy_harness/__init__.py` versions, and do not tag releases manually. Release-please owns both.
- Do not commit secrets or credentials.

## Code of conduct

Be professional and assume good faith. Technical disagreements are welcome; personal attacks are not. The project does not yet have a formal Code of Conduct document — if you need one for your organisation's compliance requirements, open an issue and we can adopt a standard one (e.g. Contributor Covenant).
