# Wave 1 rollout continuation

Date: 2026-09-20
Final report branch: `docs/wave-1-rollout-final`

## Outcome

Wave 1 is merged, released, installed and deployed. The final installed version
is `lazy-harness 0.76.3`, built from published tag `v0.76.3` at release commit
`dc0402031c367d78f850eef3bac9ec6dcd54f19e`.

The binary-first rollout completed against the installed package, not a
worktree. Its `site-packages` tree was read back and contains:

- `knowledge/project_state.py`;
- `core/repo_instructions.py`;
- portable skill projection and the indirect-symlink fix in `deploy/skills.py`;
- literal Unicode serialization for both Claude `settings.json` and
  `.claude.json`.

The final live deploy converges with chezmoi, preserves installer-owned hooks
and user-selected models, and is byte-stable across consecutive deploys. No
LazyMind vault file was changed.

## Landed changes and releases

### Review remediation

PR #413 merged as `3884064`. It fixed the review findings found after the
initial Wave 1 release:

- reject a skill ledger file or metadata directory that is a symlink;
- sanitize CommonMark headings and fences before generated project-state text
  can consume human-authored sections;
- start done retention at completion without following task symlinks;
- archive dangling or malicious symlink tasks without processing their target;
- stop non-zero when the worker cannot drain the queue.

The first CI run exposed a Python compatibility error in a test assertion:
`Path.exists(follow_symlinks=False)` is unavailable on supported Python
versions. The corrected assertion uses `not task.is_symlink()` and the complete
matrix passed. Release `v0.76.1` was then published and installed.

### Indirect profile skill links

The first installed deploy found a second concrete defect. A runtime projection
pointed into a managed profile, but that profile entry was itself a symlink to
an external catalog. Resolving the complete chain made the runtime link look
user-owned and deploy refused it.

The regression runs deploy twice with exactly that indirect layout. PR #415
merged as `df3148a`; release PR #416 published `v0.76.2` at `27586ac`. The
installed package was read back before the next live deploy, which then accepted
the existing `grill-me` projection and converged.

### Unicode convergence

The next `apply -> deploy` check found that Claude config writes used JSON's
ASCII escaping while chezmoi rendered literal Unicode. This was the already
recorded backlog item for `ensure_ascii=True`, and it blocked byte convergence.

Two RED tests covered `settings.json` and `.claude.json`. Both writers now use
`ensure_ascii=False`. PR #417 merged as `2a337f6`; release PR #418 published
`v0.76.3` at `dc04020`. The published package was installed and its two writer
call sites were verified directly in `site-packages` before deploy.

## Verification

### Code gates

- PR #413 gate: **5,241 passed** in 366.44 seconds; Ruff lint and format clean;
  MkDocs strict clean; `git diff --check` clean.
- PR #415 gate: **5,242 passed** in 374.67 seconds; the other three checks
  clean.
- PR #417 gate: **5,244 passed** in 369.80 seconds; 502 files formatted; Ruff,
  MkDocs strict and `git diff --check` clean.
- PR #417 CI passed docs plus Python 3.11, 3.12, 3.13, 3.14 and macOS 3.13.
  The same matrix passed on `main` before release PR #418 was merged.
- Final installed `lh selftest`: 70 passed, 0 failed, with the two expected
  warnings for Claude-only artifacts absent from `lazy-codex`.

### Profile and config convergence

The active deploy preserves the intended ownership split:

- lazy model: `opus`; flex model: `opus[1m]`;
- lazy and flex: 10 Moshi installer-owned hook groups each;
- Codex: 4 Moshi installer-owned groups;
- old `/opt/homebrew/bin/moshi` router commands: 0 in every profile;
- Graphify external hooks remain present;
- `lh_hook_ownership` survives chezmoi for both Claude profiles.

The first `lh deploy` under `v0.76.3` produced a clean targeted `chezmoi diff`.
A second deploy reported all system docs unchanged. SHA-256 values before and
after that second run were identical for `config.toml`, lazy settings, flex
settings and Codex hooks.

The global chezmoi diff still reports two unrelated pre-existing destination
drifts: Herdr's `sidebar_collapsed_mode` and two lines in the Flex repos note.
They were neither applied nor re-added. The three lazy-harness targets modified
by this rollout have no chezmoi diff.

### Installed ADR-059 probe

The probe used the published `v0.76.3` binary and a temporary, uniquely owned
profile link for `lazymind-projects`. The real command was
`codex debug prompt-input` in both directions:

1. Deploy created `~/.agents/skills/lazymind-projects`, pointing into the
   `lazy-codex` profile, and recorded only that name in the Codex skill ledger.
2. The model-visible skills catalog contained exactly one line beginning
   `- lazymind-projects:`.
3. Only the temporary profile link was removed; the real skill source remained
   untouched.
4. Redeploy reported `skills/lazymind-projects (no longer generated)`, removed
   the owned native projection, and left the ledger with an empty `links` list.
5. A second prompt-input probe contained zero catalog entries with that name.

The temporary directories and probe outputs were removed. The final deployed
state matches the pre-probe state, with no `lazymind-projects` entry under the
global Codex skill root and an empty Codex projection ledger.

### Queue retention and Dependabot

A real installed worker run was executed for `lazy` and `flex`. Neither queue
contained tasks older than seven days, both workers exited 0, and the completed
counts remained 1,242 and 1,074. `lh status queue` still renders `Done total`
for both profiles.

GitHub currently reports Dependabot alerts #10 and #11 for `anyio` as `fixed`,
not dismissed, with `fixed_at = 2026-09-19T21:26:09Z`. There are no open
Dependabot alerts, so no additional lockfile change was made.

## Dotfiles

Dotfiles commit `ce43d49` (`fix: reconcile agent config ownership`) is published
on `main`. It:

- preserves `model` and `lh_hook_ownership` in the modify template;
- removes the obsolete global Moshi router declarations;
- documents Moshi as installer-owned and Graphify as the remaining configured
  external hook family;
- corrects the system-doc sync hook name and ownership wording.

The modify script passes `bash -n`; both settings templates render as valid
JSON; the active config template renders and completes a real `load_config`
cycle; `git diff --check` passes. The dotfiles worktree is clean and matches
`origin/main`.

## Rollback evidence

Every live deploy created a snapshot. The final convergence snapshots are:

- `2026-09-20T11-56-47.400011`;
- `2026-09-20T11-58-20.637020`;
- `2026-09-20T11-59-52.952142` for the positive skill probe;
- `2026-09-20T12-00-41.434283` for the restored negative state.

An earlier failed deploy was rolled back with `lh deploy --rollback` before any
further reconciliation. The pre-rollout raw backups remain under
`/tmp/wave1-rollout.OO4MOc/` for this session.

## Deferred, explicitly out of scope

Two medium-priority backlog items were added without implementing them:

- audit the quality gate measured at 5,241-5,244 tests and roughly six minutes;
  accept an optimization only with at least 20% wall-time improvement,
  mutation-backed equivalent signal and no new flakes;
- standardize agent/profile naming and launcher aliases, inventory every `lcca`
  consumer, choose one separator, map `(profile, agent, bypass intent)`, and run
  real launch probes before deprecation.

The ADR-060 pilots, ADR-061 receiver/backfill/Grafana work, ADR-062 archival and
opt-in, and the historical nested-Claude `pre_compact` bug remain separate
lanes and were not started.
