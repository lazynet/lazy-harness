# AGENTS.md — lazy-harness

This file is what agents other than Claude Code load first. It carries no
rules of its own: read `CLAUDE.md` in this directory — every non-negotiable,
verification gate and prohibition there applies to every agent working in
this repository, whatever binary runs it.

Three things `CLAUDE.md` assumes that a non-Claude agent does not have:

- **`/tdd-check`** is `.claude/commands/tdd-check.md`. Run its four commands
  by hand before every commit, with its scoping:
  `uv run --frozen pytest -q`, `uv run --frozen ruff check src tests`,
  `uv run --frozen ruff format --check src tests`,
  `uv run --frozen --group docs mkdocs build --strict`.
- **`/new-worktree`** and **`/cleanup-worktree`** are
  `.claude/commands/new-worktree.md` and `.claude/commands/cleanup-worktree.md`;
  read them and run the git commands they describe.
- **`/coherence-audit`** is `.claude/commands/coherence-audit.md`; it is
  read-only and a release gate, run it as written.

One rule for any agent running inside an `lh run` pane:

- Never change the active `gh` account. If `gh` refuses with
  `must be a collaborator`, stop and report which account is active.
