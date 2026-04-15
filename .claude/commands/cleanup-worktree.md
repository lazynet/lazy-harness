---
description: Remove a merged worktree and its branch after verifying it was merged into main
argument-hint: <short-name>  (the directory name under .worktrees/, without the type prefix)
---

You are cleaning up the worktree `.worktrees/$ARGUMENTS` and its associated branch. This command must never remove unmerged work — verify first, remove second.

## Validation (do this first, in order)

1. Confirm `.worktrees/$ARGUMENTS` exists. If not, stop and tell the user nothing to clean.
2. Identify the branch associated with the worktree:
   ```bash
   git -C .worktrees/$ARGUMENTS rev-parse --abbrev-ref HEAD
   ```
   Capture this as `BRANCH`.
3. Confirm the branch has been merged into `main`. The safest check is whether every commit on `BRANCH` is reachable from `origin/main`:
   ```bash
   git fetch origin main --quiet
   git merge-base --is-ancestor "$BRANCH" origin/main
   ```
   If the check fails (exit code ≠ 0), **stop immediately** and tell the user the branch has unmerged commits. Do not offer to force-remove. Ask the user how they want to proceed.
4. Confirm the worktree has no uncommitted changes:
   ```bash
   git -C .worktrees/$ARGUMENTS status --porcelain
   ```
   If output is non-empty, stop and report the dirty state. Do not remove.

## Execute (only if every check passed)

```bash
git worktree remove .worktrees/$ARGUMENTS
git branch -d "$BRANCH"
```

Then confirm with `git worktree list` that the worktree is gone and report success.

## Reference

See `specs/workflow/worktrees.md` for the full worktree discipline.
