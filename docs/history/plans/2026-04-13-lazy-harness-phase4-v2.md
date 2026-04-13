# lazy-harness Phase 4 v2 — Relocate, Archive, Document

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Phase 4 of lazy-harness by (1) relocating profiles out of lazy-claudecode into `~/.config/lazy-harness/profiles/`, (2) shipping a MkDocs Material docs site at `lazynet.github.io/lazy-harness`, and (3) migrating all conceptual content from lazy-claudecode into lazy-harness and archiving the old repo. Cut `v0.4.0` at soak-end and `v0.5.0` at phase close.

**Architecture:** Three parts execute in a partially-ordered sequence. **G'** runs first and is filesystem-only (no framework code changes — `lh profile deploy` already reads from `~/.config/lazy-harness/profiles/`). **F** (docs) starts after G' completes and runs in parallel with **G** (content audit + archival) because they touch disjoint files. **G** depends on F being live for its archival README to link out to. Final release tags gated on selftest stability.

**Tech Stack:** Python 3.11+, click, rich, MkDocs Material, GitHub Actions, git.

**Repositories touched:**
- `~/repos/lazy/lazy-harness` — add docs/, mkdocs.yml, .github/workflows/, content pages, cut v0.4.0 + v0.5.0
- `~/repos/lazy/lazy-claudecode` — drain, commit final cleanups, tag `v-final`, archive
- Martin's dotfiles (chezmoi) — out of scope; Martin connects chezmoi to `~/.config/lazy-harness/profiles/` after G' completes

**Plan file:** Lives here during execution. During G task 6 it gets migrated to `lazy-harness/docs/history/plans/` along with its siblings. No action needed from executor — G's migration script handles it.

---

## Context: What Changed Since Phase 4 v1 Spec

The v1 spec (`2026-04-12-lazy-harness-phase4-migrate-cutover.md`) was written before these events:

1. **v0.3.5 / v0.3.6 out-of-plan work shipped:** `lh hook` CLI + builtin hooks port, `lh run` launcher, `lh profile envrc`, `lh status` (9 views), `lh statusline`, `lh profile move`, `qmd-context-gen` ported to lh scheduler, logfile rotation, FlattenSymlinksStep implementation in migrate, detector fix for `com.lazy.*` vs `com.lazynet.*` globs.

2. **Personal migration `lh migrate` executed 2026-04-12.** Tag `v0.4.0-rc1` cut. 194 tests green. `lh selftest` 30/30 post-migration. Soak week in progress (ends 2026-04-19).

3. **Profile relocation decision (2026-04-13):** Profiles move from `lazy-claudecode/profiles/` to `~/.config/lazy-harness/profiles/`. Martin connects chezmoi to the new location. This is the last acople código↔personal to break.

4. **Ground truth diverges from v1 spec expectations:**
   - Profiles in `~/.claude-lazy/` / `~/.claude-flex/` are **still symlinks** to `lazy-claudecode/profiles/*` on disk. The `FlattenSymlinksStep` either did not execute during the personal migration or was reverted. G' starts from "everything is a symlink" as ground truth, not from "flatten happened".
   - `lazy-harness` pyproject version is `0.3.6`. Tag `v0.4.0-rc1` exists but HEAD is ahead of it with 13 commits of additional work. Release promotion is **not** `rc1 → 0.4.0 final`; it is **`HEAD → 0.4.0 final`** (new tag from current HEAD after soak).
   - 2 LaunchAgents symlinked to lazy-claudecode are LazyMind territory and block archival: `com.lazynet.lazy-vault.plist`, `com.lazynet.learnings-review.plist`. These need relocation in Part G before archive.
   - Several pending deletions sit uncommitted in lazy-claudecode git status (deprecated bash scripts, `qmd-embed`/`qmd-sync` plists). G task 3 commits these.

5. **Profiles as "discard" in v1 spec is wrong.** v1 Section 5 table marks `profiles/` as `discard (personal info)`. v2 corrects: profiles **relocate** to `~/.config/lazy-harness/profiles/` via G' and are versioned by chezmoi. They are not discarded, they are moved.

6. **New open issue logged:** `lazy-harness/docs/backlog.md` already contains the `compound-loop` delta-by-index issue from session 4bc38694. Out of scope for Phase 4. Referenced here so the executor knows not to touch it.

## Execution Order

```
G' (profile relocation)         ← blocks everything; runs first
 │
 ├─► F (docs site)               ← parallel, starts after G' completes
 │
 └─► G (content + archival)      ← parallel, starts after G' completes
        │
        └─► (G depends on F being live for archival README external link)

(soak week ends ~2026-04-19)
 │
 └─► H (release)                 ← tag v0.4.0 at soak end, v0.5.0 at phase close
```

**Rationale for interleaving F and G**: F's content pages `history/genesis.md` and `history/lessons-learned.md` are written **by** Part G's content distillation. So G produces content that F consumes. They share ordering on those two pages only; all other F pages are independent.

**Soak week and G'**: G' mutates the very runtime that soak is validating. The pragmatic choice is to fold G' into the soak test: if selftest stays green for the rest of the week after G', the migration+G' combo is stable and v0.4.0 ships. If G' breaks selftest, roll back G' (it is trivially reversible — recreate symlinks pointing at the backup) and extend soak.

---

## File Structure Overview

### New files in lazy-harness

```
lazy-harness/
├── mkdocs.yml                              (new)
├── pyproject.toml                          (modified — add docs extra)
├── .github/
│   └── workflows/
│       └── docs.yml                        (new — GH Pages deploy)
├── docs/
│   ├── index.md                            (new)
│   ├── why/
│   │   ├── problem.md                      (new)
│   │   ├── memory-model.md                 (new — load-bearing page)
│   │   └── philosophy.md                   (new)
│   ├── getting-started/
│   │   ├── install.md                      (new)
│   │   ├── first-run.md                    (new)
│   │   └── migrating.md                    (new)
│   ├── reference/
│   │   ├── cli.md                          (new)
│   │   └── config.md                       (new)
│   ├── architecture/
│   │   ├── overview.md                     (new)
│   │   └── decisions/
│   │       ├── <existing framework ADRs>   (unchanged)
│   │       └── legacy/                     (new — from lazy-claudecode)
│   │           └── README.md               (new — framing page)
│   ├── history/
│   │   ├── genesis.md                      (new — origin narrative)
│   │   ├── lessons-learned.md              (new — distillation)
│   │   ├── specs/                          (new — migrated)
│   │   │   └── *.md                        (migrated from lazy-claudecode)
│   │   └── plans/                          (new — migrated)
│   │       └── *.md                        (migrated from lazy-claudecode)
│   └── backlog.md                          (unchanged — already exists)
```

### Files removed from lazy-claudecode (G cleanup)

```
lazy-claudecode/
├── adrs/                                   (migrated → lazy-harness, then removed)
├── config/                                  (discard)
├── docs/                                    (migrated or distilled, then removed)
├── launchd/                                 (emptied — 2 plists relocated, qmd plists already deleted)
├── profiles/                                (moved to ~/.config/lazy-harness/profiles/)
├── scripts/                                 (discard — superseded by lh)
├── skills/                                  (follow profiles)
├── workflows/                               (migrate still-relevant, discard rest)
├── workspace-routers/                       (discard)
├── CLAUDE.md                                (keep — gets replaced by archival README)
├── README.md                                (replaced with archival README)
└── memory/                                  (keep — runtime state, not versioned)
```

Note: `memory/` at repo root does not exist. Runtime memory lives at `~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/` and is not part of the repo. It stays put during archival.

---

# Part G' — Profile Relocation

**Goal:** Move `CLAUDE.md`, `settings.json`, `commands/`, `docs/`, `skills/` for both `lazy` and `flex` profiles from `lazy-claudecode/profiles/<name>/` to `~/.config/lazy-harness/profiles/<name>/`, and re-point `~/.claude-<name>/` symlinks at the new location. Framework code unchanged — `lh profile deploy` already reads from `config_dir() / "profiles"`.

**Reversibility:** Every step is reversible until Task 7 is committed. If anything breaks, `rm -rf ~/.config/lazy-harness/profiles/ && ln -s ~/repos/lazy/lazy-claudecode/profiles/lazy/CLAUDE.md ~/.claude-lazy/CLAUDE.md` (and equivalents) restores the original.

**Preconditions:**
- `lh` binary available on PATH
- lazy-claudecode working tree: pending deletions visible in `git status` are acceptable (will be handled in Part G); uncommitted profile edits are NOT acceptable — commit or stash them first.
- No active Claude Code sessions running (to avoid cached settings mid-move)

### Task G'-1: Pre-flight audit and backup

**Files:**
- Read: `~/.claude-lazy/`, `~/.claude-flex/`, `lazy-claudecode/profiles/`
- Create: `~/.config/lazy-harness/backups/g-prime-<ts>/`

- [ ] **Step 1: Stop any running Claude Code sessions**

Run: `ps aux | grep -i "[c]laude" | grep -v grep`
Expected: empty output. If not empty, close those sessions in their terminals before proceeding.

- [ ] **Step 2: Snapshot current symlink state of both profile dirs**

```bash
TS=$(date +%Y%m%dT%H%M%S)
BACKUP=~/.config/lazy-harness/backups/g-prime-$TS
mkdir -p "$BACKUP"
for name in lazy flex; do
  dir=~/.claude-$name
  [ -d "$dir" ] || continue
  {
    echo "## $dir"
    find "$dir" -maxdepth 1 -type l -print0 | xargs -0 -I{} sh -c 'printf "%s -> %s\n" "$1" "$(readlink "$1")"' _ {}
  } >> "$BACKUP/symlinks-before.txt"
done
cat "$BACKUP/symlinks-before.txt"
```

Expected: Shows symlinks like `~/.claude-lazy/settings.json -> /Users/lazynet/repos/lazy/lazy-claudecode/profiles/lazy/settings.json`. If any symlinks are absent or point elsewhere, stop and reconcile before continuing.

- [ ] **Step 3: Snapshot the source files via tar (preserves content even if source is deleted mid-migration)**

```bash
tar -C ~/repos/lazy/lazy-claudecode -czf "$BACKUP/profiles-source.tar.gz" profiles/
ls -lh "$BACKUP/profiles-source.tar.gz"
```

Expected: Archive created, nonzero size.

- [ ] **Step 4: Record current selftest baseline**

Run: `lh selftest > "$BACKUP/selftest-before.txt" 2>&1; echo "exit=$?"`
Expected: `exit=0`. Save `selftest-before.txt` for later diff comparison. If selftest fails here, **stop** — do not start G' on an already-broken baseline.

- [ ] **Step 5: Commit nothing; save backup directory path for subsequent tasks**

```bash
echo "$BACKUP" > /tmp/g-prime-backup-path
cat /tmp/g-prime-backup-path
```

Expected: prints the backup directory path. This path is referenced by later tasks as `$BACKUP`.

### Task G'-2: Create destination layout

**Files:**
- Create: `~/.config/lazy-harness/profiles/lazy/`, `~/.config/lazy-harness/profiles/flex/`

- [ ] **Step 1: Create empty destination dirs**

```bash
mkdir -p ~/.config/lazy-harness/profiles/lazy
mkdir -p ~/.config/lazy-harness/profiles/flex
ls -la ~/.config/lazy-harness/profiles/
```

Expected: Both dirs exist, empty.

- [ ] **Step 2: Confirm `lh profile deploy` source path**

Run: `python -c "from lazy_harness.core.paths import config_dir; print(config_dir() / 'profiles')"`
Expected: `/Users/lazynet/.config/lazy-harness/profiles`. If any other path, STOP — path resolution has diverged from the plan's assumption and G' will deploy to the wrong place.

### Task G'-3: Move lazy profile content

**Files:**
- Source: `~/repos/lazy/lazy-claudecode/profiles/lazy/`
- Destination: `~/.config/lazy-harness/profiles/lazy/`

- [ ] **Step 1: Copy (not move) lazy profile content to destination**

```bash
cp -a ~/repos/lazy/lazy-claudecode/profiles/lazy/. ~/.config/lazy-harness/profiles/lazy/
ls -la ~/.config/lazy-harness/profiles/lazy/
```

Expected: Destination contains `CLAUDE.md`, `settings.json`, `commands/`, `docs/`, `skills/` (contents match source). Using `cp -a` (not `mv`) so the source stays intact until Task G'-6 verifies success.

- [ ] **Step 2: Byte-level sanity check**

```bash
diff -qr ~/repos/lazy/lazy-claudecode/profiles/lazy/ ~/.config/lazy-harness/profiles/lazy/
echo "diff exit=$?"
```

Expected: `diff exit=0` with no output. Any diff output means copy was incomplete — abort and re-copy.

### Task G'-4: Move flex profile content

**Files:**
- Source: `~/repos/lazy/lazy-claudecode/profiles/flex/`
- Destination: `~/.config/lazy-harness/profiles/flex/`

- [ ] **Step 1: Copy flex profile content**

```bash
cp -a ~/repos/lazy/lazy-claudecode/profiles/flex/. ~/.config/lazy-harness/profiles/flex/
ls -la ~/.config/lazy-harness/profiles/flex/
```

Expected: Destination contains same layout as lazy profile.

- [ ] **Step 2: Byte-level sanity check**

```bash
diff -qr ~/repos/lazy/lazy-claudecode/profiles/flex/ ~/.config/lazy-harness/profiles/flex/
echo "diff exit=$?"
```

Expected: `diff exit=0` with no output.

### Task G'-5: Break old symlinks and redeploy

**Files:**
- Modify: `~/.claude-lazy/*` (symlinks), `~/.claude-flex/*` (symlinks)

- [ ] **Step 1: Remove the profile-content symlinks from `~/.claude-lazy/`**

Only remove items that are symlinks pointing at `lazy-claudecode/profiles/lazy/`. Leave runtime state (`projects/`, `cache/`, `logs/`, etc.) untouched.

```bash
for name in lazy flex; do
  dir=~/.claude-$name
  for item in "$dir"/*; do
    [ -L "$item" ] || continue
    target=$(readlink "$item")
    case "$target" in
      */lazy-claudecode/profiles/*) rm "$item" && echo "removed: $item";;
    esac
  done
done
```

Expected: Lines like `removed: /Users/lazynet/.claude-lazy/CLAUDE.md`, `removed: /Users/lazynet/.claude-lazy/settings.json`, etc.

- [ ] **Step 2: Verify no dangling references to lazy-claudecode in either profile dir**

```bash
find ~/.claude-lazy ~/.claude-flex -maxdepth 1 -type l -exec readlink {} \; | grep lazy-claudecode
echo "exit=$?"
```

Expected: `exit=1` (grep found nothing). If exit=0, there are still symlinks pointing at lazy-claudecode — repeat step 1 for those items specifically.

- [ ] **Step 3: Run `lh profile deploy`**

```bash
lh profile deploy
```

Expected output includes lines like:
```
  ✓ lazy/CLAUDE.md
  ✓ lazy/settings.json
  ✓ lazy/commands
  ✓ lazy/docs
  ✓ lazy/skills
  ✓ flex/CLAUDE.md
  ✓ flex/settings.json
  ...
```

If output is "No profiles directory found", the destination path in Task G'-2 was wrong; stop and reconcile.

- [ ] **Step 4: Verify new symlinks point at `~/.config/lazy-harness/profiles/`**

```bash
readlink ~/.claude-lazy/settings.json
readlink ~/.claude-lazy/CLAUDE.md
readlink ~/.claude-flex/settings.json
```

Expected: All three print paths under `~/.config/lazy-harness/profiles/{lazy,flex}/`, NOT under `lazy-claudecode`.

### Task G'-6: Post-move selftest and smoke test

**Files:**
- Read: `~/.config/lazy-harness/backups/g-prime-*/selftest-before.txt`

- [ ] **Step 1: Run `lh selftest` and diff against baseline**

```bash
BACKUP=$(cat /tmp/g-prime-backup-path)
lh selftest > "$BACKUP/selftest-after.txt" 2>&1
echo "exit=$?"
diff "$BACKUP/selftest-before.txt" "$BACKUP/selftest-after.txt"
```

Expected: `exit=0` and diff shows zero or only timestamp changes. Any check that flipped from PASS to FAIL is a blocker — proceed to rollback (see below).

- [ ] **Step 2: Smoke test lazy profile — start a short Claude Code session**

Open a new terminal, run:
```bash
CLAUDE_CONFIG_DIR=~/.claude-lazy claude --help > /dev/null
echo "exit=$?"
```

Expected: `exit=0`, no errors. Claude Code loaded settings from `~/.claude-lazy/settings.json` (which now resolves through symlink to `~/.config/lazy-harness/profiles/lazy/settings.json`).

- [ ] **Step 3: Smoke test flex profile**

```bash
CLAUDE_CONFIG_DIR=~/.claude-flex claude --help > /dev/null
echo "exit=$?"
```

Expected: `exit=0`.

- [ ] **Step 4: Verify session-context hook still injects correctly**

The most sensitive consumer of the profile layout is the `context-inject` hook. Force a fresh injection by invoking it directly:

```bash
printf '{"cwd":"/Users/lazynet/repos/lazy/lazy-claudecode"}' | lh hook run context-inject
```

Expected: JSON output with `hookSpecificOutput.additionalContext` containing the project banner. If this fails or emits empty additional context, the profile move broke hook resolution.

- [ ] **Step 5: Rollback if ANY of the above failed**

If selftest regressed or smoke tests failed:
```bash
BACKUP=$(cat /tmp/g-prime-backup-path)
# Remove new symlinks
for name in lazy flex; do
  dir=~/.claude-$name
  for item in "$dir"/*; do
    [ -L "$item" ] || continue
    target=$(readlink "$item")
    case "$target" in
      */.config/lazy-harness/profiles/*) rm "$item";;
    esac
  done
done
# Recreate old symlinks from backup record
while read -r line; do
  case "$line" in
    "## "*) continue;;
    *" -> "*) link=${line%% -> *}; target=${line##* -> }; ln -s "$target" "$link";;
  esac
done < "$BACKUP/symlinks-before.txt"
# Optionally remove the destination content
rm -rf ~/.config/lazy-harness/profiles/
lh selftest
```
STOP execution and investigate. Do not proceed to G'-7.

### Task G'-7: Clean up sources and update memory

**Files:**
- Delete: `lazy-claudecode/profiles/lazy/`, `lazy-claudecode/profiles/flex/` (sources now redundant, will be fully removed in Part G)
- Modify: `~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/project_lazy_harness.md`

- [ ] **Step 1: Do NOT delete `lazy-claudecode/profiles/` from disk yet**

Part G's cleanup task handles the git-side removal as part of the broader repo drain. Deleting here creates a midway state with no git history of the removal. Leave the source tree in place.

- [ ] **Step 2: Update project memory to reflect completed state**

Edit `~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/project_lazy_harness.md`. Under `## Pendientes conocidos` → `### Fases del plan pendientes`, update the profile-relocation bullet to note G' is executed:

```markdown
- **Profiles → ~/.config/lazy-harness/profiles/** (decisión 2026-04-13, ejecutado 2026-04-13 via G'). Movido. `~/.claude-<name>/` ahora symlinkea a `~/.config/lazy-harness/profiles/<name>/`. Martin: conectar chezmoi al nuevo location como next step (fuera del harness).
```

Also update the top-level description line to reflect soak + G' done:
```markdown
Framework v0.4.0-rc1 — migración personal + G' (profile relocation) ejecutados. Soak week en curso. Pendiente Parts F (docs) y G (archival).
```

- [ ] **Step 3: Handoff note for Martin**

Append to `~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/handoff.md`:

```markdown
## G' complete (YYYY-MM-DD)
- Profiles canonical source is now `~/.config/lazy-harness/profiles/{lazy,flex}/`.
- ACTION ITEM for Martin: connect chezmoi to `~/.config/lazy-harness/profiles/`. Out of plan scope.
- Backup of pre-move state: `~/.config/lazy-harness/backups/g-prime-<ts>/`. Retain until Part G archival completes.
```

- [ ] **Step 4: No git commit — G' is filesystem-only**

G' does not touch either repo's git tree in a way that should be committed independently. The subsequent removal of `lazy-claudecode/profiles/` happens in Part G task G-11 as part of the full drain.

---

# Part F — Documentation Site

**Goal:** Stand up a MkDocs Material site with the minimum content set from Phase 4 v1 spec Section 4, deployed to `lazynet.github.io/lazy-harness` via GitHub Actions.

**Preconditions:**
- Part G' complete (not technically necessary, but avoids having to pause mid-F to unblock G')
- `uv` available; lazy-harness repo working tree clean OR pending work is on a feature branch
- Martin has admin access to `github.com/lazynet/lazy-harness` (to enable GH Pages)

**Parallelism note:** Tasks F-1 through F-7 and F-10 through F-14 can proceed without any Part G work. Tasks F-8 (genesis.md) and F-9 (lessons-learned.md) depend on G content distillation (tasks G-8 and G-9 respectively). If executing linearly, sequence F-1..F-7, F-10..F-12, then interleave with G, then return for F-8, F-9, F-13 (deploy).

### Task F-1: Add docs dependency extra to pyproject.toml

**Files:**
- Modify: `~/repos/lazy/lazy-harness/pyproject.toml`

- [ ] **Step 1: Add `[project.optional-dependencies.docs]`**

Edit `pyproject.toml`. Find the existing `dev = [...]` section (under `[project.optional-dependencies]` or wherever it lives), and add a `docs` extra alongside it:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
]
docs = [
    "mkdocs-material>=9.5",
    "mkdocs-mermaid2-plugin>=1.1",
    "mkdocs-glightbox>=0.3",
]
```

If the file uses `[tool.uv.dev-dependencies]` instead, add an equivalent group there. Check the file structure first with `grep -n "dev\|docs\|optional" pyproject.toml`.

- [ ] **Step 2: Sync deps**

```bash
cd ~/repos/lazy/lazy-harness
uv sync --extra docs
```

Expected: Downloads and installs mkdocs-material, mermaid2, glightbox. No errors.

- [ ] **Step 3: Smoke test mkdocs CLI is available**

```bash
uv run mkdocs --version
```

Expected: Prints version like `mkdocs, version 1.6.x`.

- [ ] **Step 4: Commit**

```bash
cd ~/repos/lazy/lazy-harness
git add pyproject.toml uv.lock
git commit -m "docs: add mkdocs-material optional dependency group"
```

### Task F-2: Create mkdocs.yml with site config and nav

**Files:**
- Create: `~/repos/lazy/lazy-harness/mkdocs.yml`

- [ ] **Step 1: Write `mkdocs.yml`**

Create `~/repos/lazy/lazy-harness/mkdocs.yml` with this content:

```yaml
site_name: lazy-harness
site_description: A cross-platform harnessing framework for AI coding agents
site_url: https://lazynet.github.io/lazy-harness/
repo_url: https://github.com/lazynet/lazy-harness
repo_name: lazynet/lazy-harness
edit_uri: edit/main/docs/

theme:
  name: material
  features:
    - navigation.instant
    - navigation.tracking
    - navigation.sections
    - navigation.indexes
    - navigation.top
    - search.highlight
    - search.suggest
    - content.code.copy
    - content.action.edit
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
  icon:
    repo: fontawesome/brands/github

plugins:
  - search
  - mermaid2
  - glightbox

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:mermaid2.fence_mermaid_custom
  - pymdownx.tabbed:
      alternate_style: true
  - pymdownx.highlight
  - pymdownx.inlinehilite
  - toc:
      permalink: true
  - attr_list
  - md_in_html

nav:
  - Home: index.md
  - Why:
    - The problem: why/problem.md
    - Memory model: why/memory-model.md
    - Philosophy: why/philosophy.md
  - Getting started:
    - Install: getting-started/install.md
    - First run: getting-started/first-run.md
    - Migrating: getting-started/migrating.md
  - Reference:
    - CLI: reference/cli.md
    - Config: reference/config.md
  - Architecture:
    - Overview: architecture/overview.md
    - Decisions: architecture/decisions/
  - History:
    - Genesis: history/genesis.md
    - Lessons learned: history/lessons-learned.md
```

- [ ] **Step 2: Verify YAML parses**

```bash
cd ~/repos/lazy/lazy-harness
uv run python -c "import yaml; yaml.safe_load(open('mkdocs.yml'))"
echo "exit=$?"
```

Expected: `exit=0`. If YAML error, fix syntax before proceeding.

- [ ] **Step 3: Do NOT `mkdocs serve` yet** — nav references files that don't exist. Will smoke-test after all content pages are created.

- [ ] **Step 4: Commit**

```bash
git add mkdocs.yml
git commit -m "docs: mkdocs-material site config and nav"
```

### Task F-3: Write `docs/index.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/index.md`

- [ ] **Step 1: Write the home page**

Create `~/repos/lazy/lazy-harness/docs/index.md`:

```markdown
# lazy-harness

A cross-platform harnessing framework for AI coding agents.

`lazy-harness` turns a raw AI coding agent (Claude Code today, others planned) into a daily-driver workstation by adding the scaffolding that agents do not ship with: multi-profile isolation, a hook engine, a monitoring pipeline, a knowledge directory, a scheduler, and a session memory model that persists across conversations.

## What it gives you

- **Profiles.** Isolate separate agent setups — personal, work, client, experimental — with their own `CLAUDE.md`, `settings.json`, skills, and knowledge. Switch by directory or env var.
- **Hooks.** A cross-platform hook engine with built-in hooks for session-start context injection, pre-compact summaries, session export, and compound loop enforcement. Bring your own hooks via config.
- **Monitoring.** SQLite-backed metrics on every session: duration, message count, tools used, cost. Nine built-in `lh status` views.
- **Knowledge.** A filesystem knowledge directory for sessions and distilled learnings, optionally indexed by [QMD](https://github.com/lazynet/qmd) for semantic search.
- **Scheduler.** A unified interface over launchd, systemd, and cron. Declare recurring jobs in `config.toml`; `lh scheduler install` does the rest.
- **Migration.** `lh migrate` takes any existing Claude Code setup and upgrades it into a lazy-harness installation with a dry-run gate and full rollback.

## Quick start

```bash
uv tool install git+https://github.com/lazynet/lazy-harness
lh init                    # new install
# or
lh migrate --dry-run       # existing Claude Code setup
lh migrate
lh doctor                  # verify prerequisites
lh selftest                # verify the framework itself
```

See the [getting-started guide](getting-started/install.md) for details.

## Why this exists

Read [the problem](why/problem.md) and [the memory model](why/memory-model.md).

## Status

Framework v0.4.0 is the first stable release. Supported platforms: macOS, Linux. Supported agent: Claude Code (others planned via the adapter layer).
```

- [ ] **Step 2: Commit**

```bash
git add docs/index.md
git commit -m "docs: home page"
```

### Task F-4: Write `docs/why/problem.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/why/problem.md`

- [ ] **Step 1: Write the page**

Create `~/repos/lazy/lazy-harness/docs/why/problem.md`:

```markdown
# The problem

AI coding agents ship as a conversational interface and a file tool. That's enough for a demo. It's not enough for a daily driver.

## What's missing out of the box

When you move from "occasionally ask Claude to explain a diff" to "pair with Claude for 8 hours a day across three projects", a collection of predictable problems emerge:

- **Session amnesia.** Each conversation starts from nothing. You re-explain the project, the conventions, the constraints, the person you are. You paste the same context every day.
- **No multi-context isolation.** One global `~/.claude/` directory mixes your personal experiments, your employer's private code, your client work, and your weekend side project. There is no way to switch cleanly.
- **No observability.** How much did last week cost? Which sessions actually changed the repo? Which tools were called? You can't answer any of these.
- **Knowledge is write-only.** You learn something in a session and it dies when the window closes. There is no loop back into future sessions.
- **Recurring jobs are yours to build.** Want a pre-compact summary? A weekly knowledge review? A nightly QMD re-index? You write the scheduler glue yourself, per platform.
- **Migration is all-or-nothing.** Adopting a new convention — moving knowledge, renaming profiles, splitting a setup — means editing many files by hand and praying.

Every one of these is solvable with enough shell scripts, cron entries, and discipline. That's what `lazy-harness` is: the shell scripts, the schedulers, and the discipline, packaged.

## Why a framework and not a set of dotfiles

The early versions of this codebase lived as a personal dotfiles-style repo (`lazy-claudecode`). That worked for one user and one machine. It broke down at the seams:

- Every improvement was tangled with personal config. Sharing required untangling.
- There was no abstraction boundary between "the harness" and "Martin's setup".
- Multi-agent portability was impossible. Every path assumed Claude Code.

Extracting `lazy-harness` as a generic framework made the boundary explicit: the framework knows about **profiles**, **hooks**, **knowledge**, **monitoring**, **scheduling** — agent-agnostic concepts. Personal config (the actual `CLAUDE.md`, the specific hook scripts you want) lives in `~/.config/lazy-harness/profiles/` and is versioned with your dotfiles, completely separate from the framework code.

## What `lazy-harness` is not

- It is not a Claude Code fork. It wraps Claude Code (and in the future other agents) without modifying them.
- It is not a chat wrapper. It never proxies your messages. It only manipulates the environment around the agent.
- It is not an MCP server. It interacts with Claude Code via settings, hooks, and the filesystem.
- It is not opinionated about your workflow. Every default is overridable; every feature is opt-in via `config.toml`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/why/problem.md
git commit -m "docs: why/problem page"
```

### Task F-5: Write `docs/why/memory-model.md` (load-bearing page)

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/why/memory-model.md`

- [ ] **Step 1: Write the page**

This is the answer to "Claude Code already has memory, why do I need this?" Structure it around three temporal scales.

Create `~/repos/lazy/lazy-harness/docs/why/memory-model.md`:

```markdown
# Memory model

Claude Code has a memory primitive: the `CLAUDE.md` file. It is loaded at session start and provides static context. That is one layer of memory. `lazy-harness` adds five more, arranged across three temporal scales.

## Three scales

| Scale | Question it answers | Mechanism |
|---|---|---|
| **Short-term** — within a single session | "What is this specific session about right now?" | `CLAUDE.md`, session-start context injection, pre-compact summaries |
| **Medium-term** — across sessions in the same project | "What did I decide last time? What broke last month?" | `MEMORY.md`, `decisions.jsonl`, `failures.jsonl`, session export |
| **Long-term** — across projects, semantic | "Where did I see this pattern before? What did I learn in 2024 about X?" | Knowledge directory, QMD semantic index, distilled learnings |

## Short-term: within a session

### Session-start context injection

The `context-inject` hook runs when Claude Code starts a session. It gathers:
- Git state (current branch, dirty files, last commit)
- Project info (name, type, recent activity)
- The tail of the project's `MEMORY.md` and the last handoff note
- "Last session" summary line (timestamp, message count, topic)

This is injected as additional context alongside your first user message, so the agent starts every session already knowing where you left off. Before lazy-harness, the first 5 minutes of every session were context reconstruction. After, they are work.

### Pre-compact summaries

When Claude Code approaches its context window limit, it compacts old messages into a summary before dropping them. The default compaction is a generic LLM summary. lazy-harness's `pre-compact` hook intercepts that moment and extracts a structured summary (decisions made, files touched, open questions) that is persisted to the project's session export. The raw conversation is lost; the distilled intent is not.

## Medium-term: across sessions, same project

### `MEMORY.md` — self-maintained project memory

Every project gets a `MEMORY.md` file at `~/.claude-<profile>/projects/<project-slug>/memory/MEMORY.md`. It is an index: one line per persistent fact, each line linking to a memory file with frontmatter and a body. Facts are typed (`user`, `feedback`, `project`, `reference`) and are updated as Claude learns them during sessions.

Unlike `CLAUDE.md` (static, human-authored), `MEMORY.md` is written by Claude. It is the agent's own notepad about what it has learned about you and the project.

### Episodic memory: `decisions.jsonl` and `failures.jsonl`

Structured, append-only JSONL files that capture:
- **Decisions:** what was decided, alternatives considered, rationale, timestamp
- **Failures:** what broke, root cause, prevention, topic

These are the history the agent can grep. When you ask "why did we pick X over Y three weeks ago?", the agent doesn't have to remember; it can read it.

The `compound-loop` hook extracts these entries automatically at session end, with heuristics to filter out trivial sessions.

### Session export

Every interactive session that crosses a message threshold gets exported to `sessions/YYYY-MM-DD-<session-id>.md` — a clean transcript with frontmatter (topic, tools used, duration, cost). These exports live in the knowledge directory and can be indexed semantically.

## Long-term: across projects, semantic

### Knowledge directory

A single filesystem directory (`~/Documents/lazy-harness-knowledge` by default, configurable) contains:
- `sessions/` — exported session transcripts
- `learnings/` — distilled weekly reviews and cross-session patterns
- Anything else you drop there

This is the union of everything the harness has learned across every project, every profile.

### QMD indexing

If you have [QMD](https://github.com/lazynet/qmd) installed, `lazy-harness` configures a collection pointing at the knowledge directory. QMD indexes markdown semantically and exposes a `recall` command that works across your entire history.

The critical affordance: you can ask "when did I last debug a circular import in Python?" and get back the specific session from six months ago. The short-term memory model is stateless by design; the long-term one is where the lessons accumulate.

## How the scales compose

A new session starts:

1. **Short-term fills:** the `context-inject` hook pulls `MEMORY.md`, the last handoff, and git state.
2. **Medium-term is queryable:** Claude can read `decisions.jsonl` and `failures.jsonl` if the task warrants it.
3. **Long-term is queryable:** if the task touches unfamiliar territory, Claude can `qmd query` against the knowledge directory.

Every session also **produces** memory: exports go to knowledge, decisions/failures are appended, `MEMORY.md` is updated by the agent. The loop closes.

## What this means in practice

Before lazy-harness, my typical session pattern was:
> "Hey Claude, remember we decided X last week? No, not that, the other one. OK, the context is..."

After lazy-harness:
> "Continue."

That is the goal of the memory model.
```

- [ ] **Step 2: Commit**

```bash
git add docs/why/memory-model.md
git commit -m "docs: memory model page"
```

### Task F-6: Write `docs/why/philosophy.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/why/philosophy.md`

- [ ] **Step 1: Write the page**

Create `~/repos/lazy/lazy-harness/docs/why/philosophy.md`:

```markdown
# Philosophy

Five principles that decide what goes into `lazy-harness` and what stays out.

## 1. Separation of concerns

Each component has one job. Configs live in dotfiles (chezmoi, yadm, whatever). Personal knowledge lives in a vault. The framework itself is boring code that wires these together — it is not a kitchen sink. When a feature would blur a boundary, the answer is no.

The litmus test: can you describe the feature's responsibility in one sentence without using "and"? If not, it needs to be split or rejected.

## 2. Ship before perfect

An 80% implementation deployed on real use beats a 100% implementation on a feature branch. Every design decision is made **against the friction of current use**, not against imagined future use. Concretely:

- Release small, often. Trunk-based development.
- Dogfood immediately. Every new feature is used by the maintainer on day one.
- Reversible decisions are preferred over optimal ones. If we can roll it back in a day, we can try it today.

## 3. Aggressive simplicity

Three repeated lines are better than a premature abstraction. Abstractions earn their keep by removing real duplication, not by anticipating it. Config is TOML, not a DSL. Hooks are shell-callable, not a plugin API. The CLI is click, not a custom parser.

When a feature requires new abstractions, the abstraction is built **inside** the feature that needs it first, and only extracted when a second use case genuinely demands it.

## 4. No tech debt by accident

Debt that you chose deliberately (with an ADR) is fine. Debt that accumulated because nobody said no is not. Every PR that adds complexity without removing equivalent complexity gets a second look. "We'll clean it up later" is a commitment, and commitments get ADRs.

The [backlog file](https://github.com/lazynet/lazy-harness/blob/main/docs/backlog.md) exists specifically to make debt visible. If it is not written down, it does not count as known.

## 5. Code > docs > conversation

A decision that only lives in a conversation is a decision that will be forgotten. Decisions live in code first (made manifest by the implementation), docs second (explained for future readers), and conversation only as a last resort when neither of the above applies yet.

Docs are not optional for framework-level features. A feature without a docs page is not done.

---

These principles are why, for example, `lh migrate` has a dry-run gate and a rollback and not "intelligent auto-detection that tries to do the right thing" — the latter would violate principles 1, 3, and 4 simultaneously.
```

- [ ] **Step 2: Commit**

```bash
git add docs/why/philosophy.md
git commit -m "docs: philosophy page"
```

### Task F-7: Write `docs/getting-started/install.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/getting-started/install.md`

- [ ] **Step 1: Write the page**

Create `~/repos/lazy/lazy-harness/docs/getting-started/install.md`:

```markdown
# Installing lazy-harness

## Prerequisites

- **Python 3.11 or later.** Check with `python3 --version`.
- **[uv](https://docs.astral.sh/uv/).** The Python package manager used to install lazy-harness. Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Claude Code** (the agent lazy-harness wraps). Install from [claude.com/claude-code](https://claude.com/claude-code).
- **git** (for the install step — lazy-harness is not on PyPI yet).
- Optional: [QMD](https://github.com/lazynet/qmd) for semantic search across your knowledge directory.

## Platforms

- macOS 13+ (Apple Silicon and Intel)
- Linux (tested on Arch, Debian, Ubuntu)
- Windows: not supported yet

## Install

```bash
uv tool install git+https://github.com/lazynet/lazy-harness
```

This installs the `lh` binary into `~/.local/bin/lh` (or wherever your `uv` prefix is). Verify:

```bash
lh --version
lh doctor
```

`lh doctor` checks your system prerequisites. Expected output: all green.

## Choose your path

Two entry points depending on what is already on your machine:

### If you do NOT have an existing Claude Code setup

```bash
lh init
```

This runs an interactive wizard that creates `~/.config/lazy-harness/config.toml`, a default profile, and your knowledge directory. See [first run](first-run.md) for details.

`lh init` refuses to run on a system with existing Claude Code state. This is deliberate — it protects your data.

### If you DO have an existing Claude Code setup

```bash
lh migrate --dry-run
```

This scans your system, detects what exists (profiles, symlinks, LaunchAgents, QMD collections, knowledge directories), and prints a migration plan. Review the plan. Then:

```bash
lh migrate
```

Execution requires a recent (< 1 hour) dry-run. Migration takes a full backup first and supports `lh migrate --rollback`. See the [migrating guide](migrating.md) for the full flow.

## Upgrading

```bash
uv tool upgrade lazy-harness
```

## Uninstalling

```bash
uv tool uninstall lazy-harness
```

This removes the `lh` binary but leaves your config, profiles, knowledge directory, and data intact. To fully purge:

```bash
rm -rf ~/.config/lazy-harness ~/.local/share/lazy-harness ~/.cache/lazy-harness
```

Note: this does NOT remove your agent's config (`~/.claude/` or `~/.claude-<profile>/`). Those remain intact — lazy-harness never owns them, it only deploys into them.
```

- [ ] **Step 2: Commit**

```bash
git add docs/getting-started/install.md
git commit -m "docs: install guide"
```

### Task F-8: Write `docs/getting-started/first-run.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/getting-started/first-run.md`

- [ ] **Step 1: Write the page**

Create `~/repos/lazy/lazy-harness/docs/getting-started/first-run.md`:

```markdown
# First run

This guide walks through `lh init` from a clean machine. If you are migrating an existing Claude Code setup, see [migrating](migrating.md) instead.

## What `lh init` does

1. Refuses to run if you have existing Claude Code state (`~/.claude/`, `~/.claude-*/`, or an existing `~/.config/lazy-harness/config.toml`).
2. Asks for a profile name (default: `personal`).
3. Asks for the agent (default: `claude-code` — the only option today).
4. Asks for a knowledge directory path (default: `~/Documents/lazy-harness-knowledge`).
5. Detects QMD if present and offers to configure a knowledge collection.
6. Writes `~/.config/lazy-harness/config.toml`.
7. Creates the profile directory at `~/.config/lazy-harness/profiles/<name>/` with a minimal `CLAUDE.md` and `settings.json`.
8. Creates the knowledge directory with `sessions/` and `learnings/` subdirs.

## Running it

```bash
lh init
```

Sample session:

```
lazy-harness — initial setup

Profile name [personal]:
Agent [claude-code]:
Knowledge directory [~/Documents/lazy-harness-knowledge]:
QMD detected. Configure knowledge collection? [Y/n]: Y

✓ Config created at ~/.config/lazy-harness/config.toml
✓ Profile 'personal' created
✓ Knowledge directory ready at ~/Documents/lazy-harness-knowledge
✓ QMD collection configured

Run `lh doctor` to verify your setup.
```

## Verifying

```bash
lh doctor     # system prerequisites
lh selftest   # framework integrity
lh profile ls # list configured profiles
```

All three should exit 0 with green output.

## Starting an agent session

```bash
CLAUDE_CONFIG_DIR=~/.claude-personal claude
```

This launches Claude Code with your personal profile. The `CLAUDE_CONFIG_DIR` env var tells Claude Code to read settings from `~/.claude-personal/` instead of the global `~/.claude/`. You can alias this:

```bash
alias claude-personal='CLAUDE_CONFIG_DIR=~/.claude-personal claude'
```

## Customizing the profile

Your profile lives at `~/.config/lazy-harness/profiles/personal/`. Edit:

- `CLAUDE.md` — the project-level instructions Claude Code will load
- `settings.json` — Claude Code settings (hooks, permissions, etc.)
- `skills/` — custom skills
- `commands/` — custom slash commands

After editing, run `lh profile deploy` to refresh the symlinks into `~/.claude-personal/`.

## Versioning your profile

`lh init` does not version your profile for you. Connect it to your dotfiles manager of choice:

```bash
cd ~/.config/lazy-harness
chezmoi add profiles/
```

(or yadm, or a git submodule, or a plain git repo inside `~/.config/lazy-harness/profiles/`.)

## Next steps

- [Migrating an existing setup](migrating.md) — if you skipped here accidentally
- [CLI reference](../reference/cli.md) — every `lh` subcommand
- [Config reference](../reference/config.md) — every `config.toml` option
```

- [ ] **Step 2: Commit**

```bash
git add docs/getting-started/first-run.md
git commit -m "docs: first-run guide"
```

### Task F-9: Write `docs/getting-started/migrating.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/getting-started/migrating.md`

- [ ] **Step 1: Write the page**

Create `~/repos/lazy/lazy-harness/docs/getting-started/migrating.md`:

```markdown
# Migrating an existing setup

If you already have a Claude Code setup — vanilla (`~/.claude/`) or customized — `lh migrate` upgrades it to a lazy-harness installation without losing data.

## What gets detected

The migration detector scans for:

| Target | Location | What happens |
|---|---|---|
| Vanilla Claude Code | `~/.claude/` | Profile created, settings translated |
| Custom profile dirs | `~/.claude-<name>/` | Each becomes a lazy-harness profile |
| Symlinks into other repos | `~/.claude-<name>/*` | Flattened into real files in the profile dir |
| Deployed scripts | `~/.local/bin/lcc-*`, etc. | Removed (superseded by `lh`) |
| LaunchAgents | `~/Library/LaunchAgents/com.*` | Cataloged; optionally replaced with `lh scheduler` jobs |
| Knowledge directories | Paths referenced in existing configs | Cataloged; pointed at, not moved |
| QMD collections | `qmd status` | Reconfigured to point at the new knowledge path |

Detection is read-only and idempotent. You can run it as many times as you want without side effects.

## The dry-run gate

`lh migrate` without `--dry-run` refuses to execute unless there is a dry-run marker less than one hour old in the backup directory. This is a safety rail: you must review the plan before running it.

```bash
lh migrate --dry-run
```

Output is a human-readable plan like:

```
Detected:
  - 2 profile dirs: ~/.claude-personal, ~/.claude-work
  - 8 deployed scripts in ~/.local/bin/
  - 3 LaunchAgents (com.example.*)
  - QMD with 5 collections

Plan:
  1. Backup → ~/.config/lazy-harness/backups/<ts>/
  2. Generate config.toml with 2 profiles
  3. Relocate profiles to ~/.config/lazy-harness/profiles/
  4. Translate hooks from settings.json
  5. Replace 3 LaunchAgents with lh scheduler jobs
  6. Remove 8 script symlinks
  7. Point knowledge at ~/Documents/existing-knowledge
  8. Reconfigure 5 QMD collections
  9. Run lh selftest

Run `lh migrate` to execute this plan (within 1 hour).
```

## Executing

```bash
lh migrate
```

Each step logs what it is about to do. The executor takes a backup snapshot first and writes a rollback log as it goes.

## Rolling back

If something feels wrong after migration:

```bash
lh migrate --rollback
```

This reads the most recent rollback log and reverses every step in order. Rollback is idempotent — you can run it multiple times safely.

For an automatic rollback (if a step fails mid-execution), no action is needed — the executor does it for you and exits non-zero.

## Post-migration checklist

1. Run `lh selftest`. Every check should pass.
2. Start an agent session with your first profile. Verify context injection works: the first message should include a banner like `Session context loaded: on main | Last session: ...`.
3. If you had recurring jobs (cron / launchd), verify they still run. `lh scheduler ls` should list everything.
4. Version your profiles. Example with chezmoi:

```bash
cd ~/.config/lazy-harness
chezmoi add profiles/
```

5. Keep the backup directory until you have used the migrated setup for at least a week without issues.

## Known limitations

- **Windows** is not supported. The migration will refuse to run.
- **Arbitrary custom hooks** are best-effort translated. Complex hook chains may need manual review post-migration. Run `lh doctor` to see hook warnings.
- **Profiles containing broken symlinks** abort the migration with a clear error. Fix the underlying symlinks first, then retry.
```

- [ ] **Step 2: Commit**

```bash
git add docs/getting-started/migrating.md
git commit -m "docs: migrating guide"
```

### Task F-10: Write `docs/reference/cli.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/reference/cli.md`

- [ ] **Step 1: Dump the click CLI tree**

```bash
cd ~/repos/lazy/lazy-harness
uv run lh --help
# For each visible subcommand, also:
uv run lh init --help
uv run lh migrate --help
uv run lh selftest --help
uv run lh doctor --help
uv run lh profile --help
uv run lh profile deploy --help
uv run lh profile move --help
uv run lh hook --help
uv run lh run --help
uv run lh status --help
uv run lh statusline --help
uv run lh scheduler --help
```

Collect the output. This is the source material for the page.

- [ ] **Step 2: Write `docs/reference/cli.md`**

The page is structured as one section per subcommand. Each section is 2–4 short paragraphs: what it does, when to use it, key flags, and a small example. Do NOT paste the raw `--help` output; rewrite in narrative form.

Create `~/repos/lazy/lazy-harness/docs/reference/cli.md` with this structure:

```markdown
# CLI reference

Every `lh` subcommand, in narrative form. For canonical flag lists, run `lh <command> --help` — that is always truth; this page is context.

## Top-level

`lh` is the entry point. Global flags: `--version`, `--help`. All real work happens in subcommands.

## lh init

Interactive setup wizard for new installs. Refuses to run on systems with existing Claude Code state. See [first run](../getting-started/first-run.md).

Key flags: `--force` (reinitialize, backing up existing config).

## lh migrate

Migrate an existing Claude Code setup into lazy-harness. See [migrating](../getting-started/migrating.md).

Key flags:
- `--dry-run` — analyze and print plan, touch nothing
- `--rollback` — reverse the most recent migration

## lh doctor

Check system prerequisites (Python, uv, git, optional QMD). Returns nonzero if anything is missing.

## lh selftest

Validate the lazy-harness installation itself. Seven check groups: config integrity, profile health, hooks, monitoring, knowledge, scheduler, CLI integrity. Complementary to `lh doctor` — doctor checks your system, selftest checks the framework.

Key flags: `--json` (machine-readable), `--fix` (attempt repairs).

## lh profile

Manage profiles.

- `lh profile ls` — list configured profiles
- `lh profile deploy` — create symlinks from `~/.config/lazy-harness/profiles/<name>/` into `~/.claude-<name>/`
- `lh profile move <project> --from <src> --to <dst>` — relocate a project's history between profiles
- `lh profile envrc` — generate direnv-style `.envrc` files for easy directory-based profile switching

## lh hook

Manage hooks.

- `lh hook ls` — list installed hooks per event
- `lh hook run <name>` — invoke a hook directly (receives JSON on stdin)
- `lh hook add <name>` — register a user hook
- Built-in hooks: `context-inject`, `pre-compact`, `session-export`, `compound-loop`

## lh run

Launcher for agent binaries. Resolves the right binary for the profile and sets up `CLAUDE_CONFIG_DIR`. Most useful when aliased.

## lh status

Monitoring views over the SQLite metrics database. Nine views: daily summary, per-project, per-session, cost trends, tool usage, duration histogram, recent sessions, errors, idle time.

## lh statusline

Render a one-line status indicator for terminal prompts or tmux status bars. Stateless read-only reporter.

## lh scheduler

Unified scheduler over launchd (macOS), systemd (Linux), and cron (fallback).

- `lh scheduler ls` — list configured jobs
- `lh scheduler install` — materialize jobs from `config.toml` into the platform scheduler
- `lh scheduler uninstall` — remove materialized jobs
```

- [ ] **Step 3: Commit**

```bash
git add docs/reference/cli.md
git commit -m "docs: CLI reference"
```

### Task F-11: Write `docs/reference/config.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/reference/config.md`

- [ ] **Step 1: Read the canonical config schema**

```bash
cd ~/repos/lazy/lazy-harness
cat src/lazy_harness/core/config.py | head -200
```

This is the ground truth for config fields. The page documents each section.

- [ ] **Step 2: Write the page**

Create `~/repos/lazy/lazy-harness/docs/reference/config.md`:

```markdown
# Config reference

`~/.config/lazy-harness/config.toml` is the single source of truth for an installation. This page documents every section.

## Example (minimal)

```toml
[agent]
type = "claude-code"

[profiles]
default = "personal"

[profiles.items.personal]
config_dir = "~/.claude-personal"

[knowledge]
path = "~/Documents/lazy-harness-knowledge"

[monitoring]
db = "~/.config/lazy-harness/metrics.db"
```

## Example (full, with two profiles + QMD + scheduler + user hook)

```toml
[agent]
type = "claude-code"

[profiles]
default = "work"

[profiles.items.personal]
config_dir = "~/.claude-personal"

[profiles.items.work]
config_dir = "~/.claude-work"

[knowledge]
path = "~/Documents/lazy-harness-knowledge"

[knowledge.sessions]
subdir = "sessions"

[knowledge.learnings]
subdir = "learnings"

[monitoring]
db = "~/.config/lazy-harness/metrics.db"

[monitoring.pricing]
input_per_mtok = 3.00
output_per_mtok = 15.00

[qmd]
enabled = true

[qmd.collections.harness]
path = "~/Documents/lazy-harness-knowledge"

[[hooks.user]]
name = "custom-lint"
event = "pre-write"
path = "~/.config/lazy-harness/hooks/custom-lint.sh"

[[scheduler.jobs]]
name = "weekly-knowledge-review"
command = "lh status weekly-review"
schedule = "0 9 * * MON"
```

## Section: `[agent]`

- `type` (string, required) — the agent adapter to use. Currently only `claude-code`.

## Section: `[profiles]` and `[profiles.items.<name>]`

- `profiles.default` (string, required) — which profile is the default when no `CLAUDE_CONFIG_DIR` env is set.
- `profiles.items.<name>.config_dir` (path, required) — where the agent reads its config from. For Claude Code this is `~/.claude-<name>/`. `lh profile deploy` creates the symlinks here.

## Section: `[knowledge]`

- `path` (path, required) — root of the knowledge directory.
- `knowledge.sessions.subdir` (string, default `"sessions"`) — subdir under `path` for exported session transcripts.
- `knowledge.learnings.subdir` (string, default `"learnings"`) — subdir for distilled learnings.

## Section: `[monitoring]`

- `db` (path, required) — SQLite database path for metrics.
- `monitoring.pricing.input_per_mtok` (float, default provider-specific) — cost per million input tokens.
- `monitoring.pricing.output_per_mtok` (float, default provider-specific) — cost per million output tokens.

## Section: `[qmd]` (optional)

- `enabled` (bool, default `false`) — whether QMD integration is active.
- `qmd.collections.<name>.path` (path) — directory each QMD collection indexes.

## Section: `[[hooks.user]]`

Repeated table array for user-defined hooks.

- `name` (string) — hook identifier.
- `event` (string) — which event triggers it. Supported: `session-start`, `pre-compact`, `session-end`, `stop`, `pre-write`, `post-write`.
- `path` (path) — executable to run.

Built-in hooks are registered automatically and do not need a `[[hooks.user]]` entry. See `lh hook ls`.

## Section: `[[scheduler.jobs]]`

Repeated table array for scheduled jobs.

- `name` (string) — job identifier.
- `command` (string) — shell command to run.
- `schedule` (string) — cron-format schedule (macOS and Linux both translate this to their native scheduler).

Materialize with `lh scheduler install`.

## Paths

All path fields accept `~` and `$HOME` expansion. Absolute paths are resolved as-is.

## Environment variable overrides

- `LH_CONFIG_DIR` — overrides the config directory entirely (default: `~/.config/lazy-harness/`)
- `LH_DATA_DIR` — overrides the data directory
- `LH_CACHE_DIR` — overrides the cache directory
- `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME` — respected per XDG spec

## Reloading config

`config.toml` is read on every `lh` invocation. No daemon, no cache. Edit and run `lh selftest` to verify your change is healthy.
```

- [ ] **Step 3: Commit**

```bash
git add docs/reference/config.md
git commit -m "docs: config reference"
```

### Task F-12: Write `docs/architecture/overview.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/architecture/overview.md`

- [ ] **Step 1: Write the page**

Create `~/repos/lazy/lazy-harness/docs/architecture/overview.md`:

```markdown
# Architecture overview

A map of the codebase and the module boundaries.

## Top-level layout

```
lazy-harness/
├── src/lazy_harness/
│   ├── cli/             — click subcommands (one file per command)
│   ├── core/            — config, paths, profiles, envrc
│   ├── agents/          — agent adapter protocol + claude-code adapter
│   ├── hooks/           — hook engine, builtins, user hook loader
│   ├── monitoring/      — SQLite ingest, views
│   ├── knowledge/       — session export, QMD wrapper
│   ├── scheduler/       — launchd, systemd, cron backends
│   ├── migrate/         — detector, planner, executor, rollback, steps/
│   ├── init/            — wizard
│   ├── selftest/        — runner, checks/
│   └── deploy/          — symlink engine
├── tests/               — pytest, mirrors src structure
├── templates/           — file templates (profile scaffolds, etc.)
└── docs/                — this site
```

## Key abstractions

### `Config` and `paths`

`core/config.py` defines the typed config model, loaded from `config.toml` via `tomllib`. `core/paths.py` resolves installation directories with explicit env var > XDG > platform defaults priority. Everything downstream reads from these two modules — there is no other path resolution in the codebase.

### Agent adapter

`agents/base.py` defines a protocol that abstracts over agent-specific details: where the agent reads settings from, what format hooks use, how the agent reports session state. Today the only implementation is `agents/claude_code.py`. Adding support for another agent means implementing this protocol and registering it in `agents/registry.py`.

### Hook engine

`hooks/` is a registry + dispatcher. Built-in hooks live at `hooks/builtins/`. User hooks declared in `config.toml` are resolved via `hooks/loader.py`. The engine speaks JSON over stdin/stdout — a hook is any executable that reads a JSON event and optionally prints JSON modifications.

### Migration engine

`migrate/` is the biggest subsystem. Its shape:

```
migrate/
├── detector.py          — scans system → DetectedState
├── planner.py           — DetectedState → MigrationPlan
├── executor.py          — runs plan with backup + rollback
├── rollback.py          — rollback registry
├── state.py             — dataclasses
├── errors.py            — MigrateError subclasses
└── steps/               — one file per step type
    ├── base.py          — Step protocol
    ├── backup.py
    ├── config_step.py
    ├── profiles_step.py
    ├── hooks_step.py
    ├── ... (etc.)
```

Each step declares a forward operation and its inverse. The executor runs them in order, appending rollback entries as it goes. If any step fails, automatic rollback runs immediately.

### Selftest

`selftest/` is parallel in structure to migrate: a runner orchestrates check groups, each check group lives in `checks/`. Every check returns a `CheckResult` with status, message, and optional fix hint.

## Deployment model

`lazy-harness` is installed via `uv tool install`. The binary is `lh`, declared in `pyproject.toml` as `[project.scripts] lh = "lazy_harness.cli.main:cli"`. No compilation, no containers, no daemons.

Profiles are NOT bundled with the framework. They live at `~/.config/lazy-harness/profiles/<name>/`, owned by the user and versioned with their dotfiles. `lh profile deploy` creates symlinks from `~/.config/lazy-harness/profiles/` into `~/.claude-<name>/` so Claude Code reads them.

## Data model

Three persistent stores:

1. **Config** — `~/.config/lazy-harness/config.toml`, human-edited TOML.
2. **Metrics** — `~/.config/lazy-harness/metrics.db`, SQLite, written by the ingest pipeline, read by `lh status`.
3. **Knowledge** — user-configured directory, plain markdown files. Optionally indexed by QMD.

All three are user-owned and survive `uv tool uninstall`.

## Testing

`tests/` mirrors `src/lazy_harness/` one-to-one. Every module has a test file. Tests use pytest, run with `uv run pytest`. The framework has ~194 tests at v0.3.6. Coverage is enforced informally (every new feature adds tests; no coverage threshold tooling).

## Design decisions

For the "why" behind specific choices, see the [architecture decisions](decisions/) section.
```

- [ ] **Step 2: Create `docs/architecture/decisions/` (placeholder if empty) and `decisions/legacy/` dir**

```bash
mkdir -p ~/repos/lazy/lazy-harness/docs/architecture/decisions/legacy
```

The `legacy/` dir will be filled during Part G. For now, create a README:

```bash
cat > ~/repos/lazy/lazy-harness/docs/architecture/decisions/legacy/README.md <<'EOF'
# Legacy ADRs

ADRs in this directory were inherited from `lazy-claudecode`, the personal harness project that preceded `lazy-harness`. They are preserved here because they capture decisions and context that remain relevant to the framework, even when the specific implementation they describe has been superseded.

Each ADR is dated at its original authorship. For current framework decisions, see the sibling directory.
EOF
```

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/
git commit -m "docs: architecture overview + legacy decisions placeholder"
```

### Task F-13: Local mkdocs serve smoke test

- [ ] **Step 1: Run mkdocs serve**

```bash
cd ~/repos/lazy/lazy-harness
uv run mkdocs serve 2>&1 | tee /tmp/mkdocs-serve.log &
SERVE_PID=$!
sleep 3
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/
echo ""
kill $SERVE_PID 2>/dev/null
```

Expected: Prints `200`. If `404` or connection refused, mkdocs did not start — check `/tmp/mkdocs-serve.log` for errors (usually a broken nav link or YAML syntax).

- [ ] **Step 2: Check for nav warnings in the log**

```bash
grep -i "warning\|error" /tmp/mkdocs-serve.log
```

Expected: Warnings only for the not-yet-created `history/genesis.md` and `history/lessons-learned.md` pages (these are deferred to Part G). No other warnings. Any other warning means a broken link or missing file — fix before committing.

- [ ] **Step 3: Optional manual review**

If Martin wants to eyeball the site:
```bash
cd ~/repos/lazy/lazy-harness && uv run mkdocs serve
```
Then open `http://127.0.0.1:8000/` in a browser. Verify the nav, theme, and readable content. Ctrl-C when done.

No commit — this task is validation only.

### Task F-14: Create GitHub Actions workflow for docs deploy

**Files:**
- Create: `~/repos/lazy/lazy-harness/.github/workflows/docs.yml`

- [ ] **Step 1: Create the workflow directory**

```bash
mkdir -p ~/repos/lazy/lazy-harness/.github/workflows
```

- [ ] **Step 2: Write the workflow**

Create `~/repos/lazy/lazy-harness/.github/workflows/docs.yml`:

```yaml
name: docs

on:
  push:
    branches:
      - main
    paths:
      - 'docs/**'
      - 'mkdocs.yml'
      - 'pyproject.toml'
      - '.github/workflows/docs.yml'
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: docs-${{ github.ref }}
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install uv
        uses: astral-sh/setup-uv@v3

      - name: Set up Python
        run: uv python install 3.11

      - name: Install docs dependencies
        run: uv sync --extra docs

      - name: Build site
        run: uv run mkdocs build --strict

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 3: Commit**

```bash
cd ~/repos/lazy/lazy-harness
git add .github/workflows/docs.yml
git commit -m "ci: docs site build and deploy to GitHub Pages"
```

- [ ] **Step 4: Push and enable GH Pages**

```bash
git push origin main
```

Then **manually** (this is a Martin action, not automatable from CLI):
1. Go to `github.com/lazynet/lazy-harness/settings/pages`
2. Source: GitHub Actions
3. Save

- [ ] **Step 5: Verify deploy**

```bash
sleep 60
gh run list --workflow=docs.yml --limit 1
```

Expected: Most recent run is `completed success`. If it failed, `gh run view <id>` to inspect logs. Common failures: `--strict` catches a warning we missed → fix the broken link/nav and re-push.

Open `https://lazynet.github.io/lazy-harness/` in a browser. Expected: site renders, nav works, search works.

---

**End of Part F content pages except `genesis.md` and `lessons-learned.md`.** Those two are Part F's tasks F-15 and F-16 which sit physically in Part G (written as side effects of the content distillation). After G-8 and G-9 produce those pages, return here to commit them and re-trigger the docs workflow.

---

# Part G — Content Audit + Archival

**Goal:** Drain lazy-claudecode of all conceptual content, relocate two LazyMind LaunchAgents that block archival, distill the learnings, and archive the repo on GitHub with a v-final tag.

**Preconditions:**
- Part G' complete (profiles relocated)
- Part F tasks F-1 through F-14 complete (docs site infrastructure exists so G can write into it)
- Soak week ending or ended (archive requires selftest stability proof)

### Task G-1: Verify LazyMind plist relocations completed externally

**Context:** Martin is relocating `com.lazynet.lazy-vault.plist` and `com.lazynet.learnings-review.plist` to the `lazy-ai-tools` repo as part of his KB-administration scope work. That work happens in parallel with this plan, in a separate effort. **This plan does NOT move the plists.** It only verifies that the relocation happened before allowing G-11 to delete `lazy-claudecode/launchd/`.

**Files:**
- Read: `~/Library/LaunchAgents/com.lazynet.lazy-vault.plist`, `~/Library/LaunchAgents/com.lazynet.learnings-review.plist`

- [ ] **Step 1: Check that the LaunchAgent symlinks no longer point at lazy-claudecode**

```bash
readlink ~/Library/LaunchAgents/com.lazynet.lazy-vault.plist 2>&1
readlink ~/Library/LaunchAgents/com.lazynet.learnings-review.plist 2>&1
```

Expected: Either (a) they are real files (not symlinks), or (b) they are symlinks pointing at `lazy-ai-tools` or chezmoi-managed paths. **Neither should contain `lazy-claudecode` in the readlink output.**

If either still points at `lazy-claudecode`, G cannot proceed past G-10. Stop, confirm with Martin whether `lazy-ai-tools` relocation is complete, and re-run this check.

- [ ] **Step 2: Confirm both agents are loaded and healthy**

```bash
launchctl list | grep -E "lazy-vault|learnings-review"
```

Expected: Two lines, no nonzero exit code in the middle column. If either shows `-` in the PID column with a nonzero exit, the relocation may have broken something — escalate to Martin.

- [ ] **Step 3: No mutation — G-1 is read-only**

G-1 does not copy, move, or `launchctl unload` anything. Its sole purpose is to gate G-11 on the external work being done.

### Task G-2: (folded into G-1)

Task G-2 in v2 draft was a duplicate sibling of G-1 for a different plist. Since G-1 now checks both plists in one read-only verification, G-2 is empty. Skip directly to G-3.

### Task G-3: Commit the already-pending deletions in lazy-claudecode

**Files:**
- Modify: `lazy-claudecode/` working tree

- [ ] **Step 1: Review what's pending**

```bash
cd ~/repos/lazy/lazy-claudecode
git status
```

Expected: `D` entries for `launchd/com.lazynet.qmd-embed.plist`, `launchd/com.lazynet.qmd-sync.plist`, `scripts/_lcc-common.sh`, `scripts/hooks/*`, `scripts/lcc`, `scripts/lcc-admin`, `scripts/monitoring/*`, `scripts/qmd/*`. Plus the two `M` entries for `profiles/{flex,lazy}/settings.json`.

- [ ] **Step 2: Stage the deletions AND the profile mods**

The profile mods are edits that were made during development and should be captured before the profile directory is removed in task G-11. Stage them both:

```bash
git add -u launchd/ scripts/ profiles/
git status
```

Expected: `Changes to be committed` shows all the D lines and the 2 M lines for profiles.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: clean up deprecated scripts and qmd launchd plists

Removes legacy bash hook scripts, lcc-* tooling, monitoring shell scripts,
and qmd-{embed,sync} plists — all superseded by lh CLI. Captures final
profile tweaks before profile relocation to ~/.config/lazy-harness/."
```

### Task G-4: Create content audit checklist

**Files:**
- Create: `~/repos/lazy/lazy-claudecode/docs/archive-audit.md` (temporary — will be removed with the rest of the repo)

- [ ] **Step 1: Write the checklist**

Create `~/repos/lazy/lazy-claudecode/docs/archive-audit.md`:

```markdown
# Content audit for archival

One row per top-level directory in lazy-claudecode. Each row marked `migrate`, `distill`, or `discard` with a destination.

## Directories

- [ ] `adrs/` — **migrate** → `lazy-harness/docs/architecture/decisions/legacy/`. All ADRs kept verbatim, add framing README.
- [ ] `config/` — **discard**. Example configs superseded by lazy-harness `templates/`.
- [ ] `docs/` — **split**:
  - `docs/superpowers/specs/*.md` → **migrate** to `lazy-harness/docs/history/specs/`
  - `docs/superpowers/plans/*.md` → **migrate** to `lazy-harness/docs/history/plans/`
  - `docs/archive/*` → **discard** (superseded design notes)
  - Other `docs/*.md` → case-by-case; most **distill** into `lazy-harness/docs/history/lessons-learned.md`
- [ ] `launchd/` — **discard** (contents relocated in tasks G-1 and G-2)
- [ ] `profiles/` — **discard** (contents relocated in Part G'; directory itself removed here)
- [ ] `scripts/` — **discard** (superseded by `lh` CLI; deprecated bash already deleted in G-3)
- [ ] `skills/` — **discard** (profile-owned, already relocated with profiles in G')
- [ ] `workflows/` — **distill** still-relevant operational procedures into `lazy-harness/docs/` (where exactly depends on content); discard rest
- [ ] `workspace-routers/` — **discard** (lazynet-specific)
- [ ] `CLAUDE.md` — **discard** (replaced by archival README in G-12)
- [ ] `README.md` — **replace** with archival README in G-12

## Runtime memory (NOT in the repo, but worth noting)

- `~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/` — **keep in place**. This is runtime state, not versioned content. Not touched by archival.
- `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/LazyMind/` — **keep in place**. Vault with session exports and learnings. Independent of the archive.

## Tracking

As each row's migration is executed in subsequent tasks, check it off.
```

- [ ] **Step 2: Commit**

```bash
git add docs/archive-audit.md
git commit -m "docs: archival audit checklist"
```

### Task G-5: Migrate ADRs to `lazy-harness/docs/architecture/decisions/legacy/`

**Files:**
- Source: `~/repos/lazy/lazy-claudecode/adrs/*.md`
- Destination: `~/repos/lazy/lazy-harness/docs/architecture/decisions/legacy/`

- [ ] **Step 1: Copy all ADRs**

```bash
cp -a ~/repos/lazy/lazy-claudecode/adrs/*.md ~/repos/lazy/lazy-harness/docs/architecture/decisions/legacy/
ls ~/repos/lazy/lazy-harness/docs/architecture/decisions/legacy/
```

Expected: Lists `README.md` (from F-12) plus `0001-*.md` through `0013-*.md`.

- [ ] **Step 2: Scan for internal links that will break**

```bash
grep -rn "\.\./\|lazy-claudecode\|profiles/\|scripts/" ~/repos/lazy/lazy-harness/docs/architecture/decisions/legacy/*.md | grep -v README.md
```

Expected: Zero hits. Any hit is a relative link that pointed at the lazy-claudecode tree and will 404 in the archived site. Rewrite each to either:
- A direct mention (not a link) if the target no longer exists
- A link into the new lazy-harness docs structure

- [ ] **Step 3: Check the audit item off**

Edit `lazy-claudecode/docs/archive-audit.md`, mark `[ ] adrs/` as `[x]`.

- [ ] **Step 4: Commit both repos**

```bash
cd ~/repos/lazy/lazy-harness
git add docs/architecture/decisions/legacy/
git commit -m "docs: migrate legacy ADRs from lazy-claudecode"

cd ~/repos/lazy/lazy-claudecode
git add docs/archive-audit.md
git commit -m "docs: audit — ADRs migrated"
```

### Task G-6: Migrate specs and plans

**Files:**
- Source: `lazy-claudecode/docs/superpowers/specs/*.md`, `lazy-claudecode/docs/superpowers/plans/*.md`
- Destination: `lazy-harness/docs/history/specs/`, `lazy-harness/docs/history/plans/`

- [ ] **Step 1: Create destination dirs**

```bash
mkdir -p ~/repos/lazy/lazy-harness/docs/history/specs
mkdir -p ~/repos/lazy/lazy-harness/docs/history/plans
```

- [ ] **Step 2: Copy specs and plans**

```bash
cp -a ~/repos/lazy/lazy-claudecode/docs/superpowers/specs/*.md ~/repos/lazy/lazy-harness/docs/history/specs/
cp -a ~/repos/lazy/lazy-claudecode/docs/superpowers/plans/*.md ~/repos/lazy/lazy-harness/docs/history/plans/
ls ~/repos/lazy/lazy-harness/docs/history/specs/
ls ~/repos/lazy/lazy-harness/docs/history/plans/
```

Expected: Lists all the v1 specs and plans plus the v2 plan (this file).

- [ ] **Step 3: Add frontmatter to each migrated file** (optional but recommended)

Each file gains a top-matter note explaining context:
```markdown
> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.
```

Script it:
```bash
for f in ~/repos/lazy/lazy-harness/docs/history/{specs,plans}/*.md; do
  # Skip if already has the note
  grep -q "^> \*\*Archived" "$f" && continue
  tmp=$(mktemp)
  {
    head -1 "$f"
    echo ""
    echo "> **Archived.** This document was authored in \`lazy-claudecode\` before the rename and migration to \`lazy-harness\`. Preserved for historical context. References to files and paths may be stale."
    echo ""
    tail -n +2 "$f"
  } > "$tmp"
  mv "$tmp" "$f"
done
```

Verify:
```bash
grep -l "Archived" ~/repos/lazy/lazy-harness/docs/history/specs/*.md | wc -l
```

Expected: nonzero (all files).

- [ ] **Step 4: Add `docs/history/specs/index.md` and `docs/history/plans/index.md`**

```bash
cat > ~/repos/lazy/lazy-harness/docs/history/specs/index.md <<'EOF'
# Legacy specs

Design specs authored during the `lazy-claudecode` era. They describe the evolution of the framework from a personal harness to a generic tool.
EOF

cat > ~/repos/lazy/lazy-harness/docs/history/plans/index.md <<'EOF'
# Legacy plans

Implementation plans authored during the `lazy-claudecode` era. Paired with the specs in `../specs/`.
EOF
```

- [ ] **Step 5: Update `mkdocs.yml` nav to include specs/plans indexes**

Edit `~/repos/lazy/lazy-harness/mkdocs.yml`. Under `History:` nav, add:

```yaml
  - History:
    - Genesis: history/genesis.md
    - Lessons learned: history/lessons-learned.md
    - Specs: history/specs/index.md
    - Plans: history/plans/index.md
```

- [ ] **Step 6: Check audit item and commit**

Edit `lazy-claudecode/docs/archive-audit.md`, mark specs/plans migration done.

```bash
cd ~/repos/lazy/lazy-harness
git add docs/history/ mkdocs.yml
git commit -m "docs: migrate specs and plans from lazy-claudecode"

cd ~/repos/lazy/lazy-claudecode
git add docs/archive-audit.md
git commit -m "docs: audit — specs and plans migrated"
```

### Task G-7: Audit and distill `docs/*.md` (non-superpowers)

**Files:**
- Source: `~/repos/lazy/lazy-claudecode/docs/*.md` (not `superpowers/`, not `archive/`)
- Destination: `lazy-harness/docs/` (various)

- [ ] **Step 1: List candidates**

```bash
find ~/repos/lazy/lazy-claudecode/docs -maxdepth 1 -name "*.md" -type f
```

Expected: A handful of top-level docs (governance, repos, tooling, vault, homelab — the conditional context docs).

- [ ] **Step 2: For each file, decide migrate / distill / discard**

The conditional context docs (`governance.md`, `repos.md`, `vault.md`, `tooling.md`, `homelab.md`) are Martin-specific — they describe his workflow. **Discard** by default. If any contains reusable guidance about the framework itself, **distill** the reusable part into the relevant section of the lazy-harness docs (e.g., into `getting-started/first-run.md` or a new `guides/` page).

Decision log: write one line per file under `docs/archive-audit.md`'s "Directories" table so future reviewers can see what was chosen.

- [ ] **Step 3: Scan `docs/archive/`** — all discard.

```bash
ls ~/repos/lazy/lazy-claudecode/docs/archive/ 2>&1
```

No migration needed.

- [ ] **Step 4: Commit audit updates**

```bash
cd ~/repos/lazy/lazy-claudecode
git add docs/archive-audit.md
git commit -m "docs: audit — top-level docs and archive/ reviewed"
```

### Task G-8: Write `lazy-harness/docs/history/lessons-learned.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/history/lessons-learned.md`
- Source material: `lazy-claudecode/memory/project_memory_audit_2026_04.md`, `project_weekly_processes.md`, `project_lcc_status_python.md`, `project_claude_md_duplication.md`, and the JSONL `failures.jsonl` and `decisions.jsonl`

- [ ] **Step 1: Read the source material**

```bash
cat ~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/project_memory_audit_2026_04.md
cat ~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/project_claude_md_duplication.md
cat ~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/project_lcc_status_python.md
cat ~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/project_weekly_processes.md
```

And skim failures.jsonl for patterns:
```bash
cat ~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/failures.jsonl | jq -r '.topic' | sort -u
```

- [ ] **Step 2: Write the distilled page**

Create `~/repos/lazy/lazy-harness/docs/history/lessons-learned.md`. Structure: 5-10 short sections, each capturing a lesson the project taught. Each section answers (1) what we tried, (2) what broke, (3) what we learned, (4) how the framework reflects it today.

Template structure:

```markdown
# Lessons learned

Patterns and mistakes from the evolution of `lazy-claudecode` into `lazy-harness`. Distilled from memory audits, session exports, and postmortem notes.

## The memory pipeline grows undisciplined fast

...

## `CLAUDE.md` duplication via symlinks is a silent trap

...

## Bash scripts in monitoring code scale badly

...

## Post-deployment test passing ≠ operational readiness

...

## Plans must validate output-consumer contracts

...

## The harness vs the dotfiles boundary

...

## Session amnesia solutions compound

...
```

For each section, write 100-200 words pulling from the specific source. Do NOT paste raw failure entries — distill them into lessons with context.

If a lesson has no source material yet, leave it out. Better a short page of five real lessons than a padded page of ten invented ones.

- [ ] **Step 3: Link from `index.md` and `why/philosophy.md`**

Add a link in both. In `docs/index.md`, under "Why this exists", add:
```markdown
Read [the problem](why/problem.md), [the memory model](why/memory-model.md), and [the lessons that shaped it](history/lessons-learned.md).
```

- [ ] **Step 4: Commit**

```bash
cd ~/repos/lazy/lazy-harness
git add docs/history/lessons-learned.md docs/index.md
git commit -m "docs: distilled lessons learned from lazy-claudecode"
```

### Task G-9: Write `lazy-harness/docs/history/genesis.md`

**Files:**
- Create: `~/repos/lazy/lazy-harness/docs/history/genesis.md`

- [ ] **Step 1: Write the origin narrative**

This page is load-bearing because `lazy-claudecode` will be private and archived. The story has to live somewhere public. Write it as a short narrative (400-800 words), not a changelog.

Create `~/repos/lazy/lazy-harness/docs/history/genesis.md`:

```markdown
# Genesis

`lazy-harness` began as `lazy-claudecode`: a personal Claude Code harness, private, single-user, and deliberately unopinionated about being reusable.

The first version was a handful of bash scripts in `~/.local/bin/` — a pre-compact hook, a session exporter, a status line renderer — wired into Claude Code via `settings.json`. It was enough to prove an idea: Claude Code could be a daily driver if you gave it the scaffolding it lacked out of the box.

## The slow drift toward a framework

Over three months, `lazy-claudecode` grew organically. Each new need produced another script, another cron entry, another small abstraction. A profile system appeared when the author needed to isolate personal from work use. A monitoring pipeline appeared when the "how much did this cost" question became daily. A knowledge directory appeared when session amnesia became untenable.

What didn't appear was a boundary. Every feature was tangled with every other feature. Every path assumed one specific user on one specific machine. Upgrading from version `0.1.0` to `0.2.0` meant editing bash scripts in place and hoping the integration tests — the maintainer's daily workflow — caught the regressions.

By version `0.3.0`, the pattern was clear: the interesting half of the codebase was generic (profiles, hooks, knowledge, monitoring, scheduling) and the uninteresting half was personal (lazynet's specific `CLAUDE.md`, his specific skills, his vault paths). Mixing them in one repo had become the limiting factor.

## The extraction

The rewrite happened in four phases over two weeks:

1. **Phase 1 — bootstrap.** Stand up `lazy-harness` as a Python package with `click` for the CLI, `tomllib` for config, and a typed adapter for Claude Code. Port the core feature set (profiles, knowledge, basic monitoring).
2. **Phase 2 — hooks + monitoring.** Port the hook engine as a cross-platform system with built-in hooks. Migrate SQLite ingestion and add the `lh status` views.
3. **Phase 3 — knowledge, QMD, scheduler.** Port the knowledge directory and session exporter. Unify launchd / systemd / cron under `lh scheduler`. Add `qmd-context-gen` as a built-in scheduler job.
4. **Phase 4 — migrate + cutover.** Build `lh migrate` as the tool that took the maintainer's own `lazy-claudecode` installation and upgraded it to `lazy-harness`. Ship docs. Archive `lazy-claudecode`.

Phase 4 was the moment of truth. If `lh migrate` could not migrate the author's own machine — the project that the tool was born from — there was no chance it could work for anyone else.

It worked.

## Why this matters

`lazy-harness` is `lazy-claudecode` with the personal tangles excised. Every feature has a coherent responsibility. Every path is configurable. Every platform-specific detail sits behind an adapter. The tradeoff — a rewrite that cost two weeks of intense work — was worth it because the result is a framework, not a setup.

The original `lazy-claudecode` repo is archived read-only. It is preserved for context and for the lessons it taught, but it is no longer a living thing. The framework it became is.

If you are reading this because you are considering extracting a personal tool into a shared framework: the answer is "only when the ratio of reusable to personal exceeds one-to-one". Below that ratio, you are moving complexity around, not reducing it. Above it, the rewrite pays for itself within weeks.
```

- [ ] **Step 2: Commit**

```bash
git add docs/history/genesis.md
git commit -m "docs: genesis narrative"
```

### Task G-10: Dead-link check on migrated content

**Files:**
- Check: `~/repos/lazy/lazy-harness/docs/` entire tree

- [ ] **Step 1: Build site in strict mode**

```bash
cd ~/repos/lazy/lazy-harness
uv run mkdocs build --strict 2>&1 | tee /tmp/mkdocs-build.log
echo "exit=$?"
```

Expected: `exit=0` with zero warnings. Strict mode fails on any broken link, unrecognized nav entry, or missing file.

- [ ] **Step 2: Fix any failures**

Common failures after migration:
- Broken relative links in legacy ADRs pointing at `../../profiles/` (rewrite or remove)
- Nav entries for files that were never created (edit `mkdocs.yml` to remove)
- Specs/plans referencing each other with full paths that no longer exist (rewrite as relative links or plain mentions)

Fix iteratively: fix, rebuild, repeat until `--strict` passes clean.

- [ ] **Step 3: Manual nav sanity check**

```bash
uv run mkdocs serve &
SERVE_PID=$!
sleep 3
kill $SERVE_PID
```

In browser (if Martin wants): visit each nav item, click each link on index + memory-model + genesis pages. No 404s.

- [ ] **Step 4: Commit any link fixes**

```bash
git add -u docs/
git commit -m "docs: fix broken links in migrated content"
```

### Task G-11: Remove discarded directories from lazy-claudecode

**Files:**
- Delete: `lazy-claudecode/{adrs,config,docs,launchd,profiles,scripts,skills,workflows,workspace-routers}/`

- [ ] **Step 1: Verify audit is complete**

```bash
grep -c "\[ \]" ~/repos/lazy/lazy-claudecode/docs/archive-audit.md
echo "Remaining unchecked: $?"
```

Expected: `0` unchecked items. If any remain, stop — that item is a liability that will be lost.

- [ ] **Step 2: Delete the directories**

```bash
cd ~/repos/lazy/lazy-claudecode
git rm -r adrs/ config/ docs/ launchd/ profiles/ scripts/ skills/ workflows/ workspace-routers/
git status
```

Expected: Large list of `D` entries. Working tree now contains only `CLAUDE.md`, `README.md`, `.git/`, and possibly a few root-level files (`.gitignore`, `LICENSE`).

- [ ] **Step 3: Commit the drain**

```bash
git commit -m "chore: drain content migrated to lazy-harness

All conceptual content (ADRs, specs, plans, lessons) has been migrated to
lazy-harness/docs/. Profiles have been relocated to ~/.config/lazy-harness/.
Scripts and launchd entries have been superseded or relocated.
Repo is being archived."
```

### Task G-12: Write archival README for lazy-claudecode

**Files:**
- Replace: `~/repos/lazy/lazy-claudecode/README.md`
- Delete: `~/repos/lazy/lazy-claudecode/CLAUDE.md` (no longer meaningful)

- [ ] **Step 1: Write the archival README**

Replace `~/repos/lazy/lazy-claudecode/README.md` with:

```markdown
# lazy-claudecode (archived)

This repository was the personal Claude Code harness of [@lazynet](https://github.com/lazynet). It has been superseded by [lazy-harness](https://github.com/lazynet/lazy-harness), a generic framework for AI coding agents extracted from this project.

**Status:** archived, read-only.

All conceptual content has been migrated to lazy-harness:

- ADRs → [lazy-harness/docs/architecture/decisions/legacy/](https://lazynet.github.io/lazy-harness/architecture/decisions/legacy/)
- Specs and plans → [lazy-harness/docs/history/](https://lazynet.github.io/lazy-harness/history/)
- Lessons learned → [lazy-harness/docs/history/lessons-learned.md](https://lazynet.github.io/lazy-harness/history/lessons-learned/)
- Origin story → [lazy-harness/docs/history/genesis.md](https://lazynet.github.io/lazy-harness/history/genesis/)

Profiles were relocated to `~/.config/lazy-harness/profiles/` (lazynet's dotfiles). Bash scripts were superseded by the `lh` CLI. LaunchAgents were either ported to `lh scheduler` or relocated to their appropriate home repositories.

This repo is preserved only as a local backup. If you found this page looking for working code, go to [lazy-harness](https://github.com/lazynet/lazy-harness).
```

- [ ] **Step 2: Remove CLAUDE.md**

```bash
cd ~/repos/lazy/lazy-claudecode
git rm CLAUDE.md
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: archival README"
```

### Task G-13: Tag `v-final` and push

- [ ] **Step 1: Tag**

```bash
cd ~/repos/lazy/lazy-claudecode
git tag -a v-final -m "Final state before archival. Superseded by lazy-harness."
git tag -l | tail
```

Expected: `v-final` appears in tag list.

- [ ] **Step 2: Push everything**

```bash
git push origin main
git push origin v-final
```

Expected: Both push cleanly. If push is rejected (e.g., branch protection on main), resolve on GitHub side first.

### Task G-14: Archive repo on GitHub (manual)

This is a GitHub UI action — not automatable from CLI unless using `gh` which may or may not support the archive flag on this account.

- [ ] **Step 1: Try `gh`**

```bash
gh repo archive lazynet/lazy-claudecode --yes
```

Expected: Either succeeds (repo archived) or errors with scope/permission issue. If it succeeds, skip to step 3.

- [ ] **Step 2: Manual fallback**

If `gh` fails: navigate to `https://github.com/lazynet/lazy-claudecode/settings`, scroll to "Danger Zone", click "Archive this repository", confirm.

- [ ] **Step 3: Verify**

```bash
gh repo view lazynet/lazy-claudecode --json isArchived
```

Expected: `{"isArchived": true}`.

- [ ] **Step 4: Keep local clone in place**

Do NOT delete `~/repos/lazy/lazy-claudecode/` from disk. It is the last local backup and occupies trivial space. Future Martin thanks you.

### Task G-15: Update project memory with final state

- [ ] **Step 1: Update `project_lazy_harness.md`**

Edit `~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-claudecode/memory/project_lazy_harness.md` to reflect the closing state:

```markdown
Framework v0.5.0 — Phase 4 cerrada. lazy-claudecode archivado read-only. Docs site live en lazynet.github.io/lazy-harness. Profiles en ~/.config/lazy-harness/profiles/ gestionados por chezmoi.
```

- [ ] **Step 2: Move this plan file to lazy-harness**

The plan file currently lives at `lazy-claudecode/docs/superpowers/plans/2026-04-13-lazy-harness-phase4-v2.md`. Task G-6 already copied the whole `plans/` dir into lazy-harness. That copy is now the canonical home. Verify:

```bash
ls ~/repos/lazy/lazy-harness/docs/history/plans/2026-04-13-lazy-harness-phase4-v2.md
```

Expected: file exists. No action needed — it was migrated with the rest of `plans/`.

---

# Part H — Release

**Goal:** Cut `v0.4.0` (stable release of what exists) and `v0.5.0` (Phase 4 closure) on `lazy-harness`.

**Preconditions:**
- Soak week complete (`lh selftest` green from 2026-04-12 through 2026-04-19)
- G' complete (profiles relocated)
- Parts F and G complete if cutting v0.5.0

### Task H-1: Cut `v0.4.0`

**Files:**
- Modify: `lazy-harness/pyproject.toml`

- [ ] **Step 1: Confirm soak week completion**

```bash
lh selftest
echo "exit=$?"
```

Expected: `exit=0`. Then check there were no failed selftests during the soak week by reviewing hooks/selftest logs or just confirming Martin hasn't seen regressions.

- [ ] **Step 2: Bump version to 0.4.0**

Edit `lazy-harness/pyproject.toml`:
```toml
version = "0.4.0"
```

- [ ] **Step 3: Commit + tag**

```bash
cd ~/repos/lazy/lazy-harness
git add pyproject.toml
git commit -m "chore: bump version to 0.4.0"
git tag -a v0.4.0 -m "v0.4.0 — migrate/init/selftest, personal cutover, soak-verified"
git push origin main
git push origin v0.4.0
```

- [ ] **Step 4: Verify the deprecated rc1 tag is still there for history**

```bash
git tag -l "v0.4*"
```

Expected: `v0.4.0` and `v0.4.0-rc1` both visible. Do not delete rc1 — it is history.

### Task H-2: Cut `v0.5.0` after Parts F and G complete

- [ ] **Step 1: Confirm Parts F and G complete**

```bash
# F: docs site live
curl -s -o /dev/null -w "%{http_code}" https://lazynet.github.io/lazy-harness/
echo ""

# G: lazy-claudecode archived
gh repo view lazynet/lazy-claudecode --json isArchived
```

Expected: `200` and `{"isArchived": true}`.

- [ ] **Step 2: Bump version to 0.5.0**

Edit `lazy-harness/pyproject.toml`:
```toml
version = "0.5.0"
```

- [ ] **Step 3: Commit + tag + push**

```bash
cd ~/repos/lazy/lazy-harness
git add pyproject.toml
git commit -m "chore: bump version to 0.5.0 — Phase 4 closed"
git tag -a v0.5.0 -m "v0.5.0 — Phase 4 closed: docs, profile relocation, content archival"
git push origin main
git push origin v0.5.0
```

- [ ] **Step 4: Update `docs/index.md` status line**

Edit `docs/index.md`, change:
```markdown
Framework v0.4.0 is the first stable release.
```
to:
```markdown
Framework v0.5.0 is current. Phase 4 closes the cutover from `lazy-claudecode`.
```

```bash
git add docs/index.md
git commit -m "docs: mark v0.5.0 as current"
git push origin main
```

- [ ] **Step 5: Final memory update**

Confirm `project_lazy_harness.md` reflects v0.5.0 as current.

---

# Final verification

- [ ] `lh --version` reports `0.5.0`
- [ ] `lh selftest` passes with `exit=0`
- [ ] `https://lazynet.github.io/lazy-harness/` loads, nav works, search works
- [ ] `gh repo view lazynet/lazy-claudecode --json isArchived` reports `{"isArchived": true}`
- [ ] `readlink ~/.claude-lazy/CLAUDE.md` points at `~/.config/lazy-harness/profiles/lazy/CLAUDE.md`
- [ ] `readlink ~/.claude-flex/CLAUDE.md` points at `~/.config/lazy-harness/profiles/flex/CLAUDE.md`
- [ ] No LaunchAgent in `~/Library/LaunchAgents/` points at `lazy-claudecode`
- [ ] Phase 4 v1 spec and plan are accessible under `lazy-harness/docs/history/specs/` and `plans/`
- [ ] `docs/backlog.md` still lists the `compound-loop delta-by-index` issue — out of Phase 4 scope, carries forward into Phase 5

Phase 4 done.
