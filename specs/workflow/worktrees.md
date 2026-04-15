# Worktrees

**Rule:** Any code or docs change in this repo is made in a git worktree, not directly on `main`. This is non-negotiable.

## Why

Worktrees let a single clone host multiple branches in parallel without stashing or switching. Each task gets its own directory with its own working tree, so experiments cannot accidentally clobber each other and you can have two or more PRs in flight simultaneously without context thrash. It also makes the "one branch = one PR" discipline physical rather than aspirational.

## Layout and naming

- Worktrees live in `.worktrees/` at the repo root. The directory is git-ignored.
- Directory name matches the branch's short name: `.worktrees/<short-name>`.
- Branch name uses a conventional prefix and the same short name: `<type>/<short-name>` where `<type>` is one of:
  - `feat/` — new user-visible capability
  - `fix/` — bug fix
  - `docs/` — documentation only (published `docs/` or internal `specs/`)
  - `chore/` — housekeeping that is not `feat`/`fix`/`docs` (tooling, config, dependencies)
  - `refactor/` — code restructuring with no behaviour change

## Creating a worktree

Manual:

```bash
git worktree add .worktrees/<short-name> -b <type>/<short-name>
cd .worktrees/<short-name>
```

Preferred: use the `/new-worktree` slash command. It validates the name and runs the commands for you.

```
/new-worktree refactor/claude-md-segmentation
```

## Working inside a worktree

- Commit inside the worktree. Do not bounce back to the main clone to commit.
- Push the branch from the worktree: `git push -u origin <type>/<short-name>`.
- Open the PR from the branch.
- Keep the branch short-lived. Trunk-based discipline: small, frequent commits; merge quickly.

## Cleanup after merge

Once the PR is merged, remove the worktree **and** the local branch:

```bash
git worktree remove .worktrees/<short-name>
git branch -d <type>/<short-name>
```

Preferred: use the `/cleanup-worktree` slash command. It verifies the branch has been merged into `main` before removing, so you do not discard unmerged work by accident.

## Common mistakes to avoid

- **Do not** create a worktree inside a directory that is not git-ignored. `.worktrees/` is the only sanctioned path.
- **Do not** work on `main` and then try to "fix it with a worktree later". The rule is *any* change in a worktree — that includes one-line documentation edits.
- **Do not** let worktrees accumulate after their PRs merge. Stale worktrees confuse `git worktree list` and waste disk.
