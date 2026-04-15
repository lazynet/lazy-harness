# Workflow reference

Internal workflow documentation for contributors working inside the `lazy-harness` repo. These files are the operational "how" behind the short rules in the root `CLAUDE.md`. They live in `specs/` because they describe *how we build the framework*, not *how users of the framework should behave*. They are not published to the public docs site.

| File | What it covers |
|---|---|
| [`worktrees.md`](./worktrees.md) | Worktree creation, naming, cleanup, and the `/new-worktree` and `/cleanup-worktree` slash commands. |
| [`release-flow.md`](./release-flow.md) | How `release-please` turns conventional commits into versioned releases, what NOT to bump manually, and how to edit the release PR. |
| [`layout.md`](./layout.md) | Map of the `src/`, `tests/`, `docs/`, and `specs/` trees — where new code, tests, docs, and decision records belong. |

**TDD discipline** is not duplicated here. The repo's TDD rules follow the `superpowers:test-driven-development` skill exactly; invoke that skill via the `Skill` tool when you start any code change. The one-line reference in `CLAUDE.md` is the authoritative pointer.
