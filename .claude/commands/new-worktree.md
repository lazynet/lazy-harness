---
description: Create a git worktree and branch for a new task with correct naming
argument-hint: <type>/<short-name>  (type ∈ feat|fix|docs|chore|refactor)
---

You are creating a new git worktree for the task identified by `$ARGUMENTS`.

## Validation (do this first)

1. Confirm `$ARGUMENTS` matches the pattern `<type>/<short-name>` where `<type>` is one of `feat`, `fix`, `docs`, `chore`, `refactor`. If it does not match, stop and tell the user the expected format.
2. Extract `<short-name>` (the part after the slash). The worktree directory will be `.worktrees/<short-name>`.
3. Verify the worktree directory does not already exist: `test ! -e .worktrees/<short-name>`. If it exists, stop and tell the user to pick a different name or clean up the old worktree first.
4. Verify the branch does not already exist locally: `git show-ref --verify --quiet refs/heads/$ARGUMENTS` should fail. If the branch exists, stop and ask the user whether to reuse it or pick a new name.

## Execute

Run exactly:

```bash
git worktree add .worktrees/<short-name> -b $ARGUMENTS
```

Then report the path of the new worktree and remind the user:

- To `cd .worktrees/<short-name>` before running any further commands.
- That commits go inside the worktree, not in the main clone.
- That the worktree should be removed with `/cleanup-worktree` after the PR merges.

## Reference

See `specs/workflow/worktrees.md` for the full worktree rationale and naming conventions.
