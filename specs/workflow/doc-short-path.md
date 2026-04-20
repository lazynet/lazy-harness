# Documentation short-path

A narrow escape hatch from the worktree-for-every-change rule. Only for documentation-only edits that cannot affect how the code runs or how the project is governed.

## Why

The worktree flow (`/new-worktree` → edit → build → commit → push → PR → merge → `/cleanup-worktree`) is the right default for code: it gives every change an isolated branch, a review surface, and a clean merge. For documentation-only tweaks — fixing a typo, adding a bullet to the backlog, extending an analysis note — that overhead often exceeds the work itself. The short-path trades the per-change isolation of a worktree for direct `main` commits, scoped tightly enough that no runtime, test, build, or governance artifact can be touched through it.

## Qualification (all must hold)

A change qualifies for the short-path only when **every** item below is true:

1. **Paths touched are a subset of the allowlist:**
   - `docs/**` (published MkDocs site, excluding `mkdocs.yml`)
   - `specs/**` except the exclusions below
   - `README.md` (repo root)
2. **No excluded path is touched:**
   - `CLAUDE.md` (agent contract)
   - `specs/workflow/**` (process rules)
   - `specs/adrs/**` (accepted decisions)
   - `specs/archive/**` (frozen history — editing it is already forbidden)
   - `mkdocs.yml`
   - `.claude/**`
   - `src/**`, `tests/**`
   - `pyproject.toml`, `uv.lock`
   - `.github/**`
3. **Commit type is `docs(...)` or `chore(...)`** — both are ignored by release-please, so no accidental version bump can originate from a short-path commit.
4. **If `docs/**` is touched, `uv run --group docs mkdocs build --strict` passes locally.**
5. **The diff is self-contained** — no paired code change lives in another uncommitted edit. Mixed changes always take the full flow.

If any item fails, the change takes the full worktree + PR flow.

## The flow

From the main clone, on an up-to-date `main`:

```bash
git switch main
git pull --ff-only origin main
# edit the file(s)
# if docs/** was touched:
uv run --group docs mkdocs build --strict
git add <files>
git commit -m "docs(scope): short description"
git push origin main
```

No branch, no worktree, no PR.

## What the short-path deliberately excludes

| Path                      | Why it is excluded                                                                                 |
|---------------------------|----------------------------------------------------------------------------------------------------|
| `CLAUDE.md`               | Defines how agents behave in this repo. A change here changes the contract; review is mandatory.   |
| `specs/workflow/**`       | Defines the contributor process itself. Changing it through the process it governs is the point.  |
| `specs/adrs/**`           | Decisions of record. PR history is part of the decision audit trail.                              |
| `mkdocs.yml`              | Misconfiguration breaks the public site build; deserves a CI run behind a PR.                     |
| `.claude/**`              | Slash commands, agent config — affects tooling behaviour.                                          |
| `src/**`, `tests/**`      | Code. Always full flow with TDD.                                                                   |
| `pyproject.toml`, `uv.lock` | Dependencies and packaging. Version-sensitive; always full flow.                                 |
| `.github/**`              | CI/CD. A bad change here breaks everyone's builds.                                                 |

## When in doubt

Default to the worktree flow. The short-path is an optimisation for the obvious cases, not a judgement call for edge ones. "I think this qualifies" is not the same as "every item on the list holds" — if the answer is not immediate, take the worktree.
