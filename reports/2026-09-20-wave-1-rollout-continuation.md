# Wave 1 rollout continuation

Date: 2026-09-20
Branch: `fix/wave-1-review-findings`

## Outcome

Wave 1 was already landed before this continuation. The stale implementation
branch head `7055f64` and the squash commit on `main`, `57222b4`, have the same
tree `eece907406b4ffa4fd6a9c673d8f452dd60ff8e1`. Release `v0.76.0` is installed
from its published tag, and its site-packages tree contains project-state,
repository-instruction and portable-skill deployment modules.

The rollout did not continue against `v0.76.0`. Independent review found
concrete defects in the released paths, all reproduced against the installed
binary before implementation:

- a valid skill ownership ledger symlink, or a symlinked ledger metadata
  directory, could overwrite an external file;
- model text could create Markdown fences or CommonMark H2 forms that made a
  later sync consume human-authored PRJ sections;
- a task older than seven days retained its old timestamp when moved to
  `done/`, so it could be pruned immediately after completion;
- timestamping symlink tasks followed their external target;
- archive failures retried the same task indefinitely and `main()` later
  reported `queue empty` with exit 0;
- dangling task symlinks caused a tight rescan loop.

The fix rejects ledger paths whose file or metadata directory is a symlink,
sanitizes all relevant CommonMark H2 and fence forms, refuses legacy generated
sections containing fences, starts retention at completion without following
symlinks, archives symlink tasks without processing them, and stops with a
non-zero result when the queue cannot be drained.

## TDD and review evidence

- Initial RED: four regressions failed for direct ledger symlinks, unclosed
  generated fences, indented H2 boundaries and completion timestamps.
- Review REDs covered symlinked metadata directories, tab and empty H2 forms,
  legacy closed fences spanning human content, symlink timestamps, archive
  failures, dangling task symlinks and the worker's final exit diagnostic.
- Expanded affected suites: **262 passed**.
- Mutation checks removed the direct and parent ledger guards, fence
  sanitization/refusal, CommonMark H2 recognition, completion timestamp reset,
  dangling-symlink handling and the worker result check. Every corresponding
  regression failed, and each mutation was restored manually.
- Two independent rereviews were run. The first closed its Markdown and
  symlink-timestamp findings with no further regression. The adversarial review
  produced the last four cases above, which were reproduced and remediated.

## Final gate

- `uv run --frozen pytest -q`: **5241 passed** in 366.44 seconds.
- `uv run --frozen ruff check src tests`: passed with no findings.
- `uv run --frozen ruff format --check src tests`: 502 files already formatted.
- `uv run --frozen --group docs mkdocs build --strict`: passed. Material's
  upstream MkDocs 2.0 banner was informational; the strict build had no error.
- `git diff --check`: passed.

## Rollout state

Previously gathered evidence remains valid:

- Dependabot alerts #10 and #11 for AnyIO were fixed, not dismissed.
- The real retention run pruned only completed tasks older than seven days and
  `lh status queue` retained the `Done total` field.
- No ADR-059 appearance/disappearance probe has run.
- No profile deploy, chezmoi apply, vault write or live skill-ledger mutation ran
  in this continuation.

The deploy remains pending behind a new release containing this fix and a
reviewed dotfiles reconciliation. The live lazy settings preserve `model: opus`
and a `Notification` hook that the current managed source does not reproduce.
The durable dotfiles change must preserve `model` and reconcile Moshi external
declarations before `lh deploy`. Chezmoi has `git.autoPush = true`, so its apply
requires explicit authorization before it may propagate repository changes.

## Required next action

The active GitHub account is still `lazynet`, but `gh auth status` reports its
token invalid. Re-authenticate that account without switching accounts, then
push this branch, open and merge its PR, wait for release-please, install the
new release, verify site-packages, and only then resume the reviewed
dotfiles/profile rollout and bidirectional ADR-059 probe.

## Authorization

Commit `9a3515a` exists locally and the worktree was clean immediately after
the commit. The subsequent `git push -u origin fix/wave-1-review-findings`
request was rejected by the permission reviewer because publishing a new remote
branch requires explicit user approval. The command did not run and no remote
state changed.

The user explicitly authorized publishing `fix/wave-1-review-findings` to
`origin`. The same authorization covers, after the corrected release is
installed, the reviewed dotfiles source reconciliation, the potentially
auto-pushed `chezmoi apply`, the binary-first profile deploy and the reversible
ADR-059 skill probe.

A separate medium-priority backlog item now scopes a future quality-gate audit.
Its measured baseline is 5,241 tests in approximately six minutes; it requires
at least a 20% wall-time improvement with mutation-backed equivalent signal and
no new flakes, otherwise the current gate stays unchanged.

The first CI run on PR #413 found one test-only compatibility defect. The
dangling-symlink regression used `Path.exists(follow_symlinks=False)`, which is
not accepted by Python 3.11 or 3.13. Production behavior had already completed;
the portable assertion now checks `not task.is_symlink()`, which directly proves
the link left the pending queue without depending on its missing target.
