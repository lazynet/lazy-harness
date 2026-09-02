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
3. Confirm the branch has been merged into `main`. Fetch first, then apply the checks
   below **in order** — the first one that succeeds proves the merge:

   ```bash
   git fetch origin main --quiet
   ```

   a. **Ancestry** — succeeds for fast-forward and merge-commit workflows:

   ```bash
   git merge-base --is-ancestor "$BRANCH" origin/main
   ```

   b. **Content equivalence** — the check that covers squash merges, which collapse the
   branch into a single commit that is not an ancestor of anything. Compare the branch
   against `origin/main`, restricted to the files the branch actually touched, so
   unrelated work landing on `main` afterwards does not pollute the comparison:

   ```bash
   FILES=$(git diff --name-only "origin/main...$BRANCH")
   if [ -z "$FILES" ]; then
     echo "MERGED: branch contributes no changes"
   elif git diff --quiet origin/main "$BRANCH" -- $FILES; then
     echo "MERGED: branch content already present on origin/main"
   else
     echo "UNMERGED"
   fi
   ```

   If **both** checks fail, **stop immediately** and tell the user the branch has
   unmerged commits. Do not offer to force-remove. Ask the user how they want to proceed.

   The content check is deliberately biased toward false negatives: if `main` modified
   the same files again after the squash landed, it reports `UNMERGED` even though the
   branch is merged. That is a stop-and-ask, never a silent delete. Confirm with
   `gh pr list --head "$BRANCH" --state merged` before overriding by hand.

4. Confirm the worktree has no uncommitted changes:
   ```bash
   git -C .worktrees/$ARGUMENTS status --porcelain
   ```
   If output is non-empty, stop and report the dirty state. Do not remove.

## Execute (only if every check passed)

```bash
git worktree remove .worktrees/$ARGUMENTS
git branch -D "$BRANCH"
```

`-D`, not `-d`: git's own notion of "merged" is ancestry, so `-d` refuses to delete a
squash-merged branch for the same reason the ancestry check fails. The validation
above is what makes the forced delete safe — never run it without passing step 3.

Then confirm with `git worktree list` that the worktree is gone and report success.

## Reference

See `specs/workflow/worktrees.md` for the full worktree discipline.
