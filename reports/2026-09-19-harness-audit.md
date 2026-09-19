# Harness audit — 2026-09-19 (lazy-harness 0.74.1)

Scope: the three deployed profiles (`lazy`, `flex`, `lazy-codex`), every git
repository under `~/repos/lazy/`, the Codex configuration under `~/.codex-lazy`,
and the memory pipeline. Every check was run by hand from the main session;
findings were verified by listing or running, never by reading names.

## Outcome

`lh doctor` passes. Symlinks, hook command resolution, system-doc assembly,
QMD collection references, JSONL stores and the chezmoi source are all clean.
Four items were resolved in-session; the rest are recorded here as backlog
input, each with the evidence that produced it.

## Resolved in this session

- Removed four dangling symlinks in `~/repos/lazy/.claude/` that still pointed
  into the pre-rename repository (`CLAUDE.md`, `commands`, `docs`,
  `settings.json`). `settings.local.json` was kept. Closes the backlog entry
  "Symlink roto a la era pre-rename".
- Purged stray backup files in the runtime roots: `settings.json.bak*`,
  `settings.json.pre-engram-dedupe`, `settings.json.pre-moshi-restore`,
  `.claude.json.bak-engram`, a zero-byte `.claude.json.tmp.*`,
  `config.toml.f9-backup`, `config.toml.pre-cleanup-20260918`. None was
  chezmoi-managed. `~/.claude-flex/skills.bak/` was moved to the session
  scratchpad instead of deleted: the `pre-tool-use-security` hook blocks a
  recursive `rm` there and the agent correctly declined to route around it.
- Rewrote the `audit-harness` skill against the ADR-055 layout (segmented
  `head.md` / `_common/*.md` / `tail.md`, `claude-code/` subtree, `shared/docs`),
  added the `lazy-codex` profile and a repository sweep, dropped the hidden
  `Explore` subagents, and replaced `du` (aliased to `dust` in this shell) with
  `/usr/bin/du`.

## Deferred — needs a decision or a worktree

### 1. `queue/done/` has no retention

| profile | files | size | older than 7 days |
| ------- | ----: | ---: | ----------------: |
| lazy    | 10575 | 41M  | 9203              |
| flex    | 9038  | 35M  | 7812              |

`compound_loop_worker.py` and `compound_loop.py` only ever `move_to_done`;
nothing prunes. Growth is linear in sessions. Options: a retention sweep in the
worker (age or count based, tested through a full enqueue → done → prune cycle),
or a `lh knowledge queue prune` subcommand wired into the scheduler. Either way
the diagnostic in `lh status` should report the `done/` count so the metric
measures the resource that grows.

### 2. Profiles name skills they do not install (ADR-059 implementation)

Verified by grepping each generated system doc against its skills directory:

- `flex/CLAUDE.md` names `lazymind-projects` and `rightsize-claude-md`;
  `flex/claude-code/skills/` holds only `graphify`, `synced`,
  `verify-before-done`. The `lazymind-projects` procedure is declared shared
  across profiles in `_common/common.md`.
- `lazy-codex/AGENTS.md` names `lazymind-projects` and `graphify`; Codex reads
  skills from `~/.agents/skills`, where neither exists (`~/.codex-lazy/skills/`
  is empty except `.system`). `qmd`, `herdr` and `grill-me` are reachable there.

ADR-059 deferred the projection until a profile skill had to run outside Claude
Code. That condition is now met by `lazymind-projects` under Codex. The audit
skill now checks this pairing on every run.

### 3. Proposal queue is full

Eleven `claude-md` proposals have been pending since 2026-09-15 and the queue
drops new ones while full, so the compound loop has recorded nothing for four
days. Drain with `lh memory proposals list` and accept/reject each; consider
raising the cap or auto-expiring proposals older than N days with a rejection
reason, so a full queue never silently disables capture again.

### 4. Codex hook trust is keyed by position

`~/.codex-lazy/config.toml` stores 31 `[hooks.state."hooks.json:<event>:<group>:<index>"]`
hashes. The hash is not a plain SHA-256 of the command string nor of the hook
or group JSON (ten normalisations tried, zero matches), so `lh doctor` is right
to report it as undeterminable. Two consequences worth recording in the Codex
adapter notes:

- Reordering or inserting a hook in `hooks.json` shifts every later index and
  invalidates its approval silently. `lh deploy` should keep hook order stable
  across releases, or the doctor should diff index → command against the last
  deploy and warn on a shift.
- Hooks do fire today: `~/.codex-lazy/queue/` holds a task enqueued this session
  and 67 in `done/`. That empirical check (a fresh `.task` after a Codex Stop)
  is the only trust probe available and is now part of the audit skill.

Only four repositories are `trusted` in the Codex config (`lazy-harness`,
`lazy-ansible`, `lazy-desktop-manager`, `lazy-hermes`); `dotfiles` and
`lazy-ai-tools` are registered for graphify but not trusted.

### 5. Repository hygiene

- `lazy-ansible`: worktree `.worktrees/claude-md-rescate` on branch
  `docs/claude-md-rescate-backlog`, not merged, plus one merged branch not
  deleted.
- `lazent`: `.worktrees/chore` and `.worktrees/feat`, two dirty files.
- `lazy-everythingapp`: `.worktrees/m5-api`, twelve dirty files, no remote.
- `lazy-ai-tools`: two branches already merged into `main`, not deleted.
- `lazy-desktop-manager`: two dirty files.
- graphify graphs were behind HEAD in `lazy-harness`, `lazy-ansible` and
  `dotfiles`; the four-hourly `graphify-update` job covers this without action.

### 6. Profile asymmetries (report only, no verdict)

- `flex` carries three commands `lazy` does not: `decision`, `handoff`,
  `onepage`.
- `lazy` carries skills `flex` does not: `audit-harness`, `grill-me`, `herdr`,
  `lazymind-projects`, `qmd`, `recall-cowork`, `rightsize-claude-md`.
- Models differ by design (`claude-fable-5-1[1m]` vs `opus[1m]`).
- No `flex.env` / `lazy-codex.env` under `~/.config/lazy-harness/secrets`;
  both inherit ambient credentials. Doctor reports this as a warning.

## Verified clean

- All symlinks in `~/.claude-lazy`, `~/.claude-flex`, `~/.codex-lazy` resolve
  (backups excluded); runtime `settings.json` matches its source byte for byte.
- 31 hook commands per profile resolve to an executable (`lh`, `graphify`,
  `moshi`, `herdr-agent-state.sh`).
- `CLAUDE.md` / `AGENTS.md` equal `head.md` + `common.md` + `<agent>.md` +
  `tail.md` for all three profiles.
- Every `docs/*.md` named in `tail.md` exists; every QMD collection named in the
  lazy profile exists in `qmd status`; no `flex-*` reference in the lazy profile.
- `MEMORY.md` has no orphan links; all 84 JSONL stores under
  `lazy-knowledge/memory/` parse line by line.
- `chezmoi diff ~/.config/lazy-harness/profiles` is empty.
- `lh memory rightsize`: no lazy-side file over 200 lines / 12 KB.
- Pre-rename residues outside `specs/archive/` are historical (`CHANGELOG.md`,
  ticked backlog items, migrate-detector fixtures).
