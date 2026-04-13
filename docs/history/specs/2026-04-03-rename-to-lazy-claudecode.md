# Rename lazy-control-tower → lazy-claudecode

> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.


**Date:** 2026-04-03
**Status:** accepted
**Supersedes:** ADR-001 (scope redefinition)

## Context

lazy-control-tower was created as a governance repo for the entire dev environment (ADR-001). Over time, 8 of 10 ADRs, all scripts, all hooks, all profiles, and all skills became Claude Code specific. The repo is no longer a "control tower" — it is the harness engineering system for Claude Code.

The term "harness" comes from the insight that the software layer around the model (hooks, skills, memory pipeline, context management) matters more than the model itself for real-world performance.

## Purpose (new)

> **lazy-claudecode** is the harness engineering system for lazynet's Claude Code setup. It contains profiles, hooks, skills, memory pipeline, CLI tools, and monitoring — the software layer that makes Claude Code work the way I want.

### In scope

- Claude Code profiles (CLAUDE.md, settings.json per account)
- Hooks (SessionStart, Stop, compound-loop, session-export)
- Skills (recall-cowork, future skills)
- CLI tools (lcc, lcc-admin)
- Monitoring (lcc-status, pricing, token stats)
- Memory pipeline (compound-loop-worker, learnings-review, session-context)
- QMD integration (context-gen, collections for CC data)
- LaunchAgents that support the harness
- ADRs about Claude Code architecture decisions
- Deploy system (deploy.sh)
- Workspace routers (CLAUDE.md per workspace)

### Out of scope

- Dotfiles and tool configs (chezmoi)
- Personal knowledge (LazyMind/Obsidian)
- General tool governance (future repo)
- Projects that Claude Code works on

## Changes

### Remove

- `inventory/` — documentation without consumers, not CC-specific

### Archive

- `docs/superpowers/specs/*` → `docs/archive/specs/`
- `docs/superpowers/plans/*` → `docs/archive/plans/`

These are historical artifacts. Refs to "lazy-control-tower" inside them stay as-is.

### Update functional refs

Files with hardcoded "lazy-control-tower" that need updating:

| File | What changes |
|------|-------------|
| `CLAUDE.md` (root) | Name, purpose, structure description |
| `scripts/deploy.sh` | Cosmetic echo |
| `scripts/_env.sh` | Comment |
| `scripts/qmd/qmd-context-gen.sh` | Collection name + path |
| `profiles/lazy/CLAUDE.md` | Conditional ref |
| `profiles/lazy/docs/repos.md` | Repo table |
| `profiles/lazy/docs/governance.md` | Title and content |
| `workspace-routers/lazy-claude.md` | Conditional ref |
| `skills/recall-cowork/SKILL.md` | QMD collection name |
| `profiles/lazy/commands/recall.md` | QMD collection name |
| `workflows/qmd-collections.md` | Collection name |
| `adrs/001-alcance-control-tower.md` | Status → superseded by ADR-011 |
| `adrs/README.md` | Table entry for ADR-001, new ADR-011 |
| Active ADRs (003-010) | Find-replace "lazy-control-tower" → "lazy-claudecode" |

### Keep as-is

- `lcc` / `lcc-admin` — acronym works for both names
- `docs/archive/` — historical refs stay with old name
- Auto-memory path — Claude resolves this automatically per project

### New files

- `adrs/011-rename-to-lazy-claudecode.md` — this decision as ADR

### Structure after rename

```
lazy-claudecode/
├── adrs/              — Architecture Decision Records
├── config/            — Tool configs (profiles.example)
├── docs/
│   ├── archive/       — Historical specs and plans
│   │   ├── specs/
│   │   └── plans/
│   └── superpowers/   — Future specs
├── launchd/           — LaunchAgents for the harness
├── profiles/          — CLAUDE.md + settings.json per profile
│   ├── lazy/
│   ├── flex/
│   └── shared/
├── scripts/           — CLI tools, hooks, monitoring
│   ├── hooks/
│   ├── monitoring/
│   ├── qmd/
│   ├── lcc
│   ├── lcc-admin
│   └── deploy.sh
├── skills/            — Claude Code skills
├── workflows/         — Operational procedures
└── workspace-routers/ — Lightweight CLAUDE.md per workspace
```

## Git / GitHub migration

1. Rename repo on GitHub: `lazy-control-tower` → `lazy-claudecode`
2. Rename local directory: `~/repos/lazy/lazy-control-tower/` → `~/repos/lazy/lazy-claudecode/`
3. Update QMD collection: rename `lazy-control-tower` → `lazy-claudecode` in `~/.config/qmd/index.yml`
4. Update any external refs (lazy-ai-tools README)

## Risks

- **Auto-memory path**: Claude stores project memory under a hash of the CWD. After rename, a new memory directory is created. Mitigation: copy memory files from old path to new.
- **GitHub redirects**: GitHub auto-redirects old repo URLs. No broken links.
- **QMD re-index**: Collection rename requires `qmd reindex` after updating index.yml.

## Decision

Rename to lazy-claudecode. The repo's actual content has been 100% Claude Code harness engineering for weeks. The name should match the reality.
