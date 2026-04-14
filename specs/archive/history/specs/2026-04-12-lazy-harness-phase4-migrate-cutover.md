# lazy-harness Phase 4 — Migrate & Cutover

> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.


**Date:** 2026-04-12
**Status:** Design approved, ready for implementation plan
**Version target:** lazy-harness v0.4.0
**Approach:** Migration-First

## Context

lazy-harness v0.3.0 is feature-complete: framework bootstrap, hooks engine, monitoring, knowledge directory, and cross-platform scheduler are all implemented and tested (110 tests, 44 Python files). What remains is Phase 4 — the cutover from the personal `lazy-claudecode` repo to the generic `lazy-harness` framework.

Phase 4 differs from previous phases in kind, not degree. Phases 1-3 were construction (new code, new tests). Phase 4 is migration — the risk is not "it doesn't compile" but "I broke my daily workflow". The scope therefore combines two dimensions:

- **Framework dimension:** generic features any future user will need (`lh migrate`, `lh init`, `lh selftest`, navigable docs)
- **Operational dimension:** lazynet's personal migration from lazy-claudecode to lazy-harness, used as the first real test case

Both dimensions are designed together, in clearly separated sections.

## Goals

- Ship `lh migrate` as a safe, automated migration tool with dry-run gate and rollback
- Ship `lh init` as a minimal wizard for new users that detects and protects existing setups
- Ship `lh selftest` as end-to-end validation of a lazy-harness installation
- Migrate lazynet's personal setup from lazy-claudecode to lazy-harness without disrupting daily workflow
- Publish navigable user documentation via MkDocs Material on GitHub Pages
- Migrate all conceptual content (ADRs, specs, lessons learned) from lazy-claudecode into lazy-harness before archival — lazy-claudecode is private and will not be publicly accessible
- Archive the lazy-claudecode repo as read-only, with all reusable knowledge preserved in lazy-harness

## Non-Goals (v0.4.0)

- Container validation / Dockerfile (deferred to v0.5.0)
- Adapters for non-Claude-Code agents (Copilot, Codex, Cursor)
- Windows support — macOS + Linux only
- PyPI publishing — install remains `uv tool install git+...`
- Web UI or dashboard
- Template-based init (`--template minimal|standard|full`)
- Multi-profile agent-agnostic CLI switching (adapter infra stays ready, but no user-facing command)
- Full `concepts/` and `guides/` documentation sections (incremental post-v0.4.0)

## Architecture Overview

Phase 4 adds three new commands to the CLI and a documentation site:

```
lh migrate      — migration engine (detector + planner + executor + rollback)
lh init         — new-user wizard with existing-setup detection
lh selftest     — end-to-end framework validation

docs/           — MkDocs Material site, deployed to GitHub Pages
```

Internal modules added:

```
src/lazy_harness/migrate/
├── detector.py         — scans system for existing setups
├── planner.py          — builds MigrationPlan from detection results
├── executor.py         — runs plan steps with backup/rollback
├── rollback.py         — rollback manager
└── steps/              — individual migration step implementations

src/lazy_harness/selftest/
├── runner.py           — orchestrates check groups
└── checks/             — individual check implementations (config, profile, hooks, monitoring, knowledge, scheduler, cli)

src/lazy_harness/init/
└── wizard.py           — interactive wizard with detection guard
```

## Section 1: `lh migrate` — Migration Engine

### Command Surface

```
lh migrate --dry-run    Analyze current state, print plan, touch nothing
lh migrate              Execute plan (requires a recent dry-run)
lh migrate --rollback   Undo the last migration
```

### Detection (Migration Detector)

The detector scans the system and builds a `DetectedState` object. It looks for:

| Target | Location | Signal |
|---|---|---|
| Claude Code vanilla | `~/.claude/` | config dir without custom profiles |
| lazy-claudecode setup | `~/.claude-{lazy,flex}/` + symlinks | profiles, settings.json, skills |
| lazy-harness previous install | `~/.config/lazy-harness/` | existing `config.toml` |
| Deployed scripts | `~/.local/bin/lcc-*` | symlinks to old repo |
| LaunchAgents | `~/Library/LaunchAgents/com.lazy.*` | plist files |
| Knowledge / sessions | paths referenced in existing configs | directory with exported markdown |
| QMD availability | `qmd` in PATH | qmd status responds |

Detection is read-only and idempotent. Its output is a structured report used by both `migrate` and `init`.

### Migration Plan

Based on detection, the planner generates an ordered `MigrationPlan` of steps. Each step declares its forward operation and its inverse (for rollback).

Default step order:

1. **Backup** — snapshot everything that will be touched into `~/.config/lazy-harness/backups/<timestamp>/`
2. **Config** — generate `config.toml` from detected state
3. **Profiles** — copy `CLAUDE.md` + `settings.json` into the new layout
4. **Skills** — move skills into the framework's skills directory
5. **Hooks** — translate hooks from settings.json into lazy-harness hook format
6. **Scheduler** — replace manually-installed LaunchAgents with `lh scheduler` jobs
7. **Scripts** — remove old `~/.local/bin/lcc-*` symlinks
8. **Knowledge** — point knowledge path at the existing directory (do not move files)
9. **QMD** — reconfigure collections if QMD is present
10. **Validate** — run `lh selftest` post-migration

### Dry-Run Gate

`lh migrate` without `--dry-run` first fails with:

```
Error: No recent dry-run found.
Run `lh migrate --dry-run` to review the migration plan before executing.
```

The gate is enforced by a `.last-dry-run` marker file in the backup directory containing a timestamp. If the marker is older than 1 hour, the gate requires a fresh dry-run. This prevents accidental execution while allowing legitimate "review then run" flows.

### Rollback

Each executed step appends its inverse operation to `rollback.json` in the backup directory. Two rollback paths:

- **Automatic:** if any step fails mid-execution, the executor runs rollback for all completed steps in reverse order and exits with a non-zero code.
- **Manual:** `lh migrate --rollback` reads the most recent `rollback.json` and executes it. Useful if the migration completed but the user wants to revert.

Rollback restores from the backup snapshot and undoes filesystem changes. It does not undo destructive operations that cannot be reversed (e.g., deleted files already purged) — the backup is the source of truth.

### Output

Dry-run produces a human-readable plan:

```
Detected:
  - lazy-claudecode profiles: lazy, flex
  - 8 deployed scripts in ~/.local/bin/
  - 3 LaunchAgents (com.lazy.*)
  - QMD with 9 collections

Plan:
  1. Backup → ~/.config/lazy-harness/backups/2026-04-12T14-00-00/
  2. Generate config.toml with 2 profiles
  3. Copy profiles lazy, flex
  4. Copy 14 skills
  5. Translate 4 hooks from settings.json
  6. Replace 3 LaunchAgents with lh scheduler jobs
  7. Remove 8 script symlinks
  8. Point knowledge at ~/Documents/lazy-knowledge
  9. Reconfigure 9 QMD collections
 10. Run lh selftest

Run `lh migrate` to execute this plan (within 1 hour).
```

## Section 2: `lh init` — New-User Wizard

### Command Surface

```
lh init           Interactive wizard (default)
lh init --force   Reinitialize, backing up existing config
```

### Flow

**Step 1 — Guard against existing state.** Before any prompt, check:

| Condition | Action |
|---|---|
| `~/.config/lazy-harness/config.toml` exists | Error: "lazy-harness is already configured. Use `lh init --force` to reinitialize (existing config will be backed up)." Exit. |
| `~/.claude/` exists with content | Error: "Detected existing Claude Code setup. To preserve your history, use `lh migrate` instead of `lh init`." Exit. |
| `~/.claude-*/` directories exist | Same as above. |
| No existing setup | Proceed to wizard. |

**Step 2 — Wizard.** Sequential prompts:

1. **Profile name** — default `personal`
2. **Agent** — default `claude-code` (only option today; forward-compatible)
3. **Knowledge directory** — default `~/Documents/lazy-harness-knowledge`
4. **QMD integration** — only if `qmd` is in PATH: "QMD detected. Enable knowledge indexing? [Y/n]"

**Step 3 — Generation.**

- Create `~/.config/lazy-harness/config.toml` with collected values
- Create profile directory
- Create knowledge directory if missing
- If QMD enabled: create a QMD collection pointing at the knowledge directory

**Step 4 — Output.**

```
✓ Config created at ~/.config/lazy-harness/config.toml
✓ Profile 'personal' created
✓ Knowledge directory ready at ~/Documents/lazy-harness-knowledge
✓ QMD collection configured

Run `lh doctor` to verify your setup.
```

### Rationale

The detection guard is the core feature. The dominant failure mode of migration tools is silently overwriting an existing setup. `lh init` refuses to run on a populated system and redirects the user to `lh migrate`. This makes `init` and `migrate` explicitly separate user journeys — you cannot accidentally take the wrong one.

## Section 3: `lh selftest` — End-to-End Validation

### Command Surface

```
lh selftest           Run all checks, human-readable output
lh selftest --json    Structured output for CI / scripting
lh selftest --fix     Attempt to repair fixable issues (recreate dirs, reinstall symlinks)
```

### Check Groups

**1. Config integrity**
- `config.toml` exists and parses
- All declared profiles have their directory
- `agent` type is valid and has an adapter
- All referenced paths exist

**2. Profile health** (per profile)
- `CLAUDE.md` exists
- `settings.json` is valid JSON
- Symlinks to `~/.claude-<name>/` resolve
- Skills directory is traversable

**3. Hooks**
- Built-in hooks are registered
- User hooks declared in `config.toml` resolve to executable files
- Dry-run each hook (no side effects) to detect syntax errors

**4. Monitoring**
- SQLite DB exists, schema is current
- Can read at least one recent session (if any exist)
- Pricing config is valid

**5. Knowledge**
- Knowledge path exists and is writable
- Sub-dirs `sessions/` and `learnings/` present
- If QMD is configured: `qmd status` responds

**6. Scheduler**
- Backend detected correctly (launchd / systemd / cron)
- Jobs declared in `config.toml` are installed
- Installed jobs match declared jobs (no drift)

**7. CLI integrity**
- All `lh *` subcommands respond to `--help` without errors
- Version match between binary and package

### Output

```
Config integrity       ✓ (4/4)
Profile 'personal'     ✓ (3/3)
Hooks                  ✗ (2/3)
  ✗ user hook 'custom-lint' not executable
Monitoring             ✓ (3/3)
Knowledge              ✓ (3/3)
Scheduler              ⚠ (2/3)
  ⚠ job 'weekly-export' declared but not installed (run `lh scheduler install`)
CLI integrity          ✓ (8/8)

Summary: 24 passed, 1 failed, 1 warning
```

Exit code: 0 if all checks pass (warnings allowed), 1 if any check fails.

### Relationship to `lh doctor`

- `lh doctor` validates **system prerequisites** (Python version, `uv` present, `qmd` optional, etc.)
- `lh selftest` validates **lazy-harness itself is working**

They are complementary. A user with a broken system runs doctor. A user unsure if the framework is healthy runs selftest.

## Section 4: Documentation — MkDocs Material + GitHub Pages

### Site Structure

```
docs/
├── index.md
├── why/
│   ├── problem.md
│   ├── philosophy.md
│   └── memory-model.md
├── getting-started/
│   ├── install.md
│   ├── first-run.md
│   └── migrating.md
├── concepts/
│   ├── profiles.md
│   ├── hooks.md
│   ├── knowledge.md
│   ├── monitoring.md
│   └── scheduler.md
├── guides/
│   ├── custom-hooks.md
│   ├── custom-skills.md
│   └── multi-profile.md
├── reference/
│   ├── cli.md
│   ├── config.md
│   └── adapters.md
├── architecture/
│   ├── overview.md
│   └── decisions/
│       ├── <new-framework-adrs>.md
│       └── legacy/          — ADRs migrated from lazy-claudecode
└── history/
    ├── genesis.md
    ├── lessons-learned.md
    └── specs/               — original lazy-claudecode design specs
```

### Key Pages

**`why/memory-model.md`** — The single most important page. Explains what memory improvements the harness enables:

- **Short term (current session):** context injection at startup (git state, project info), pre-compact summaries before context window flushes
- **Medium term (cross-session, same project):** self-maintained `MEMORY.md`, episodic memory via `decisions.jsonl` and `failures.jsonl`
- **Long term (cross-project, semantic):** knowledge directory + QMD indexing, session exports with frontmatter, distilled learnings

This is the page that answers "but Claude Code already has memory, why do I need this?"

**`why/philosophy.md`** — Distills the design principles: separation of concerns, ship-before-perfect, aggressive simplicity, hybrid architecture (framework + dotfiles). These principles are the reasons behind specific decisions, not arbitrary style preferences.

**`architecture/decisions/`** — ADRs rewritten in formal Context → Decision → Consequences format, focused on the framework (not on lazynet's personal setup). Original ADRs are preserved in `architecture/decisions/legacy/` with context framing.

**`history/genesis.md`** — A narrative page that tells the origin story honestly: lazy-harness started as lazy-claudecode, the personal harness of @lazynet. It was extracted into a generic framework when the patterns proved reusable. This page is **load-bearing** because lazy-claudecode is a private repo and will not be publicly accessible — the narrative has to live in lazy-harness or it is lost.

### Tooling

- **MkDocs Material** as the generator (`mkdocs-material`)
- **Plugins:** `mkdocs-mermaid2-plugin` (diagrams), `mkdocs-glightbox` (images)
- **GitHub Actions workflow:** deploys `mkdocs gh-deploy` on push to `main`
- **Local preview:** `uv run mkdocs serve`

### Minimum Content for v0.4.0

Shipping v0.4.0 does not require every page to be written. Minimum set:

- `index.md`
- `why/problem.md`, `why/memory-model.md`, `why/philosophy.md`
- `getting-started/install.md`, `first-run.md`, `migrating.md`
- `reference/cli.md` (auto-generable from click)
- `reference/config.md`
- `history/genesis.md`, `history/lessons-learned.md`
- All migrated legacy ADRs and specs in place

`concepts/` and `guides/` sections are filled in incrementally after v0.4.0.

## Section 5: Content Migration and Archival of lazy-claudecode

### Why Full Migration Is Required

lazy-claudecode is a private repo. After archival, it will not be publicly accessible. Therefore anything of conceptual or reference value must be copied into lazy-harness **before** archival. Linking from the archived repo is not useful because readers of lazy-harness will not be able to follow those links.

### Content Migration Audit

Before archival, every directory in lazy-claudecode is reviewed and each item is marked **migrate**, **distill**, or **discard**:

| Source | Destination | Treatment |
|---|---|---|
| `adrs/` (all ADRs) | `lazy-harness/docs/architecture/decisions/legacy/` | migrate verbatim, add context README |
| `docs/superpowers/specs/*` | `lazy-harness/docs/history/specs/` | migrate verbatim |
| `docs/*.md` (design docs) | `lazy-harness/docs/history/` or `docs/architecture/` | migrate relevant, distill rest |
| Memory audit docs, weekly reviews | `lazy-harness/docs/history/lessons-learned.md` | distill into a single lessons page |
| `workflows/` (operational procedures) | `lazy-harness/docs/guides/` | migrate still-relevant, discard obsolete |
| `profiles/` (personal CLAUDE.md) | — | discard (contains personal info, not reusable) |
| `workspace-routers/` | — | discard (specific to lazynet's workspace) |
| `scripts/` (`deploy.sh`, `lcc-*`) | — | discard (superseded by `lh` CLI) |
| `memory/` (project memory) | — | discard (specific to old setup) |

The audit is tracked as a checklist. Archival cannot proceed until every row is marked done. "Discard" means **not migrated to lazy-harness** — the content remains in the archived lazy-claudecode repo, it is simply not carried forward because it has no value to external users or contains personal data.

### Archival Steps

1. **Execute content migration audit.** Every row marked migrate / distill / discard with destination verified.
2. **Run personal migration.** Execute `lh migrate --dry-run` then `lh migrate` on lazynet's machine. Validate with `lh selftest`.
3. **Soak period.** Run normally for one week. If `lh selftest` fails at any point, halt and fix.
4. **Write archival README** for lazy-claudecode:
   ```markdown
   # lazy-claudecode (archived)

   This repo was the personal Claude Code harness of @lazynet.
   It evolved into lazy-harness, a generic framework for AI coding agents.

   Status: archived, read-only.

   All conceptual content (ADRs, design docs, lessons learned) has been
   migrated to lazy-harness. This repo is preserved only as a local backup.
   ```
5. **Tag final state:** `git tag v-final -m "Final state before archival. Superseded by lazy-harness."` and push.
6. **Archive on GitHub:** Settings → Archive this repository.
7. **Keep local clone** in `~/repos/lazy/lazy-claudecode/` as backup. Do not delete from disk in v0.4.0.

### Archival Gate

Archival happens only when all of the following are true:

- `lh migrate` executed successfully on lazynet's machine
- `lh selftest` passed green for one week of normal use
- Content migration audit checklist is complete
- Docs site is live at `lazynet.github.io/lazy-harness`
- Minimum documentation content is published
- lazy-harness v0.4.0 tagged and pushed

## Section 6: Scope and Done Criteria

### In Scope for v0.4.0

**Code:**
- `lh migrate` with detection, plan, dry-run gate, execution, rollback
- `lh init` with existing-setup detection and wizard
- `lh selftest` with seven check groups
- Internal modules: migration detector, planner, executor, rollback manager, selftest runner

**Documentation:**
- MkDocs Material configured at repo root
- GitHub Actions workflow for automatic deployment to GitHub Pages
- Minimum content set (listed in Section 4)
- Legacy ADRs migrated to `docs/architecture/decisions/legacy/`
- Original specs migrated to `docs/history/specs/`
- `docs/history/lessons-learned.md` distilled and written

**Operational:**
- Personal migration executed successfully
- `lh selftest` green for one week
- Content migration audit complete
- lazy-claudecode archived on GitHub

### Out of Scope (Explicit)

- Container validation / Dockerfile
- Non-Claude-Code agent adapters
- Windows support
- PyPI publishing
- Web UI
- Template-based init
- User-facing multi-agent CLI switching
- Full `concepts/` and `guides/` content

### Done Criteria for v0.4.0

Release cut when all are true:

1. `lh migrate --dry-run` and `lh migrate` work end-to-end on lazynet's machine
2. `lh init` works in a clean environment (VM or alternate user account)
3. `lh selftest` passes green post-migration
4. Docs site is live at `lazynet.github.io/lazy-harness`
5. Minimum documentation content is published
6. Content migration audit checklist is signed off
7. lazy-claudecode archived on GitHub
8. `v0.4.0` tag pushed

## Open Questions

None at design time. Any questions that emerge during implementation will be recorded in the implementation plan.

## Next Step

Invoke `superpowers:writing-plans` to produce the implementation plan for v0.4.0.
