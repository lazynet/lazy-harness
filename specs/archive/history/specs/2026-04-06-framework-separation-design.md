# Framework Separation: claude-harness public repo

> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.


**Date:** 2026-04-06
**Status:** Draft
**Decision:** Split lazy-claudecode into a public reusable framework (`claude-harness`) and personal config managed via chezmoi.

## Problem

lazy-claudecode contains both generic framework code (scripts, hooks, monitoring, QMD integration) and personal configuration (profiles, vault paths, skills with hardcoded collections, LaunchAgents with hardcoded labels). This makes the repo impossible to share or open-source.

## Decision

**Option C1:** Public framework repo + personal config as chezmoi overlay.

- New repo `claude-harness` — generic framework, templates, QMD integration
- Personal profiles, skills, routers, LaunchAgents → chezmoi dotfiles repo
- Clean separation: framework never touches `~/.claude-{name}/` directly
- QMD as core component with guided onboarding, not optional add-on

## Architecture

### Repo structure: `claude-harness`

```
claude-harness/
├── scripts/
│   ├── lcc                       # Profile router (reads ~/.config/lcc/profiles)
│   ├── lcc-admin                 # Profile + QMD management CLI
│   ├── _env.sh                   # Shared env (defaults overrideable, no personal paths)
│   ├── _lcc-common.sh            # Shared helpers
│   ├── deploy.sh                 # scripts + completions + launchd only
│   ├── hooks/
│   │   ├── session-context.sh
│   │   ├── compound-loop.sh
│   │   ├── compound-loop-worker
│   │   ├── claude-session-export.sh
│   │   └── pre-compact.sh
│   ├── monitoring/
│   │   ├── lcc-status            # Python + rich dashboard
│   │   └── _lcc_*.py
│   ├── completions/
│   │   └── _lcc
│   ├── qmd/
│   │   └── qmd-context-gen.sh    # QMD helpers (generic)
│   ├── claude-statusline.sh
│   └── learnings-review.sh
├── skills/
│   ├── recall/
│   │   └── SKILL.md              # Template: QMD recall with placeholder collections
│   └── audit/
│       └── SKILL.md              # Template: harness audit with parametrized paths
├── profiles/
│   └── example/
│       ├── CLAUDE.md             # Annotated template with sections and guidance
│       ├── settings.json         # Hooks, permissions, MCP servers (example)
│       └── docs/
│           └── README.md         # How to use progressive disclosure docs
├── workspace-routers/
│   └── example-claude.md         # Template: conditional doc loading pattern
├── launchd/
│   └── templates/
│       ├── label.qmd-sync.plist      # {LABEL_PREFIX}, {BIN_DIR}, {HOME}
│       ├── label.qmd-embed.plist
│       ├── label.learnings-review.plist
│       └── label.lazy-vault.plist
├── adrs/                         # ADRs (scrubbed of personal refs)
├── config/
│   ├── profiles.example
│   └── pricing.example.json
├── docs/
│   └── ...
├── CLAUDE.md                     # Repo instructions (generic)
└── README.md                     # Onboarding + quickstart
```

### What moves to chezmoi (personal config)

```
dotfiles/
├── dot_config/lcc/
│   └── profiles.tmpl                     # chezmoi template → ~/.config/lcc/profiles
├── private_dot_claude-lazy/
│   ├── CLAUDE.md.tmpl                    # Profile rules, identity, stack
│   ├── settings.json.tmpl               # Hooks, MCP servers (qmd, gws), permissions
│   ├── docs/
│   │   ├── repos.md
│   │   ├── homelab.md
│   │   ├── vault.md
│   │   ├── governance.md
│   │   └── tooling.md
│   ├── commands/                         # Custom slash commands
│   └── skills/
│       ├── recall-cowork/SKILL.md        # Instance with real QMD collections
│       └── audit-harness/SKILL.md        # Instance with real paths
├── private_dot_claude-flex/
│   ├── CLAUDE.md.tmpl
│   ├── settings.json.tmpl
│   ├── docs/
│   │   └── restrictions.md
│   └── skills/
├── repos/lazy/dot_claude/
│   ├── CLAUDE.md                         # Workspace router for ~/repos/lazy/
│   └── ...
├── repos/flex/dot_claude/
│   ├── CLAUDE.md                         # Workspace router for ~/repos/flex/
│   └── ...
└── Library/LaunchAgents/
    ├── com.lazynet.qmd-sync.plist.tmpl
    ├── com.lazynet.qmd-embed.plist.tmpl
    ├── com.lazynet.learnings-review.plist.tmpl
    └── com.lazynet.lazy-vault.plist.tmpl
```

## Interface contract: framework <-> personal config

### Conventions the framework expects

| Convention | Location | Format |
|---|---|---|
| Profile registry | `~/.config/lcc/profiles` | `[*]name  config-dir  root-paths...` |
| Profile directory | `~/.claude-{name}/` | Contains `CLAUDE.md`, `settings.json`, optionally `docs/`, `commands/`, `skills/` |
| Framework scripts | `~/.local/bin/` | Symlinks managed by `deploy.sh scripts` |
| Hooks in settings.json | Each profile's `settings.json` | Reference scripts at `$HOME/.local/bin/` |
| QMD binary | `$PATH` | `qmd` command available |
| LaunchAgents (macOS) | `~/Library/LaunchAgents/` | Managed by user (chezmoi or manual) |

### What each side provides

**Framework (claude-harness):**
- `lcc` — profile router based on CWD matching against `~/.config/lcc/profiles`
- `lcc-admin` — init (profiles + QMD), list, migrate, doctor, move-projects, pricing
- Hooks — session-context, compound-loop, session-export, pre-compact
- Monitoring — lcc-status, statusline
- QMD helpers — qmd-context-gen and related scripts
- `deploy.sh` — symlinks scripts to `~/.local/bin/`, completions to `~/.zfunc/`, loads LaunchAgents
- Templates — profiles, skills, routers, LaunchAgents as starting points

**Personal config (chezmoi or manual):**
- Profile contents (`CLAUDE.md`, `settings.json`, `docs/`)
- Instantiated skills (from templates or custom)
- Workspace routers (instantiated from template)
- LaunchAgents (instantiated from templates)
- `~/.config/lcc/profiles` (the profile registry file)
- QMD collections config

### No-overlap rule

`deploy.sh` **never writes** to `~/.claude-{name}/`. It only manages `~/.local/bin/`, `~/.zfunc/`, and LaunchAgent loading. Profile contents are the user's responsibility.

## deploy.sh changes

### Removed functions
- `deploy_profiles()` — profiles managed by user (chezmoi/manual)
- `deploy_routers()` — routers managed by user (chezmoi/manual)

### Remaining functions
- `deploy_scripts()` — unchanged (symlinks to `~/.local/bin/`)
- `deploy_completions()` — unchanged (symlinks to `~/.zfunc/`)
- `deploy_launchd()` — simplified: loads plists already present in `~/Library/LaunchAgents/`, does not copy from repo

### Subcommands
```
deploy.sh scripts      # symlinks → ~/.local/bin/
deploy.sh completions  # symlinks → ~/.zfunc/
deploy.sh launchd      # load/reload LaunchAgents already in ~/Library/LaunchAgents/
deploy.sh all          # all three
```

## _env.sh changes

```bash
# Remove hardcoded vault default
export LCT_VAULT="${LCT_VAULT:-}"

# Keep timezone overrideable (harmless default)
export TZ="${LAZY_TIMEZONE:-UTC}"

# Keep other vars unchanged (already parameterized)
```

Scripts that use `$LCT_VAULT` must guard against empty value and skip gracefully.

## QMD integration (core component)

### lcc-admin init — extended flow

```
$ lcc-admin init

Setting up lcc profiles.

Default profile name [default]: lazy
Config dir for 'lazy' [~/.claude-lazy]:
Root paths for 'lazy' (space-separated) [~]: ~/repos/lazy ~

Add another profile? [y/N] y
Profile name: flex
Config dir [~/.claude-flex]:
Root paths: ~/repos/flex

Add another profile? [y/N] n

── QMD Setup ──
Vault/knowledge base path: ~/Documents/MyVault
Collection prefix [default]: lazy

Configure collections? [Y/n] y
  1) projects  — ~/Documents/MyVault/Projects
  2) resources — ~/Documents/MyVault/Resources
  3) meta      — ~/Documents/MyVault/Meta
  Add more? [y/N] n

Generate sync schedule (LaunchAgent/cron)? [Y/n] y
  Sync interval [4h]: 4h
  Embed interval [6h]: 6h

Written to ~/.config/lcc/profiles
QMD collections configured: lazy-projects, lazy-resources, lazy-meta
LaunchAgent templates generated in ~/Library/LaunchAgents/
```

### lcc-admin doctor — QMD checks

```
=== lcc-admin doctor ===

[OK] Config file: ~/.config/lcc/profiles
[OK] Claude binary: ~/.local/share/claude/versions/...
[OK] ~/.claude → ~/.claude-lazy

Profiles:
  [OK] lazy (default) — ~/.claude-lazy (12 projects)
  [OK] flex — ~/.claude-flex (3 projects)

QMD:
  [OK] qmd binary found: /opt/homebrew/bin/qmd
  [OK] Collection lazy-projects: 142 docs, last sync 2h ago
  [OK] Collection lazy-resources: 89 docs, last sync 2h ago
  [OK] Collection lazy-meta: 234 docs, last sync 2h ago
  [WARN] Collection lazy-meta: embeddings stale (last embed 3d ago)

LaunchAgents:
  [OK] com.lazy.qmd-sync (loaded, every 4h)
  [OK] com.lazy.qmd-embed (loaded, every 6h)

All checks passed.
```

### QMD as MCP server

The example `settings.json` includes QMD MCP config:

```json
{
  "mcpServers": {
    "qmd": {
      "command": "qmd",
      "args": ["mcp"]
    }
  }
}
```

This is profile config (not framework), but the example profile ships with it enabled and documented.

## Skill templates

### skills/recall/SKILL.md

Same structure as current `recall-cowork` but:
- Collection table uses placeholders: `{prefix}-projects`, `{prefix}-resources`, `{prefix}-meta`
- No Desktop Commander references (that was Cowork-specific)
- Instructions to customize: "Edit the collections table to match your QMD setup"
- Search modes (temporal, topic, graph) preserved as-is — they're generic patterns

### skills/audit/SKILL.md

Same 3-agent parallel structure but:
- Paths use variables: `$REPO_DIR`, `$PROFILE_DIR`, `$VAULT_DIR`
- Vault section marked as optional ("skip if no Obsidian vault configured")
- LaunchAgent section parametrized by `$LABEL_PREFIX`
- Profile names read from `~/.config/lcc/profiles` instead of hardcoded

## LaunchAgent templates

Template format in `launchd/templates/`:

```xml
<!-- label.qmd-sync.plist -->
<!-- Instantiate with: LABEL_PREFIX, HOME, BIN_DIR -->
<plist>
  <dict>
    <key>Label</key>
    <string>{LABEL_PREFIX}.qmd-sync</string>
    <key>ProgramArguments</key>
    <array>
      <string>{BIN_DIR}/qmd-sync.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>14400</integer>
    <key>StandardOutPath</key>
    <string>{HOME}/Library/Logs/lcc/qmd-sync.log</string>
  </dict>
</plist>
```

Users instantiate these via chezmoi templates, `lcc-admin init`, or manually.

## Migration plan

Staged migration. At no point does the current setup break.

### Stage 1 — Create public repo
1. Create `claude-harness` repo, clean `git init`
2. Copy framework code: scripts/, hooks/, monitoring/, qmd/, completions/
3. Refactor `deploy.sh`: remove `deploy_profiles()` and `deploy_routers()`
4. Create `profiles/example/`, skill templates, router template, launchd templates
5. Extend `lcc-admin init` with QMD setup flow
6. Extend `lcc-admin doctor` with QMD checks
7. Clean `_env.sh` defaults
8. Scrub ADRs of personal references, copy to new repo
9. Write README with quickstart
10. Write CLAUDE.md for the new repo

**Validation:** clone on a clean machine, run `lcc-admin init`, verify `lcc-admin doctor` passes.

### Stage 2 — Migrate personal config to chezmoi
1. Create chezmoi templates for `profiles/lazy/`, `profiles/flex/`
2. Create chezmoi templates for workspace routers
3. Create chezmoi templates for instantiated skills (recall-cowork, audit-harness)
4. Create chezmoi templates for LaunchAgents (com.lazynet.*)
5. Create chezmoi template for `~/.config/lcc/profiles`
6. Run `chezmoi apply`, verify everything lands correctly

**Validation:** `lcc-admin doctor` still passes, `lcc-admin list` shows profiles.

### Stage 3 — Switchover
1. Point local `deploy.sh` invocations to `claude-harness` clone
2. Remove scripts from `lazy-claudecode` that are now in `claude-harness`
3. Verify full flow: `chezmoi apply` + `deploy.sh all` + `lcc-admin doctor`
4. Archive `lazy-claudecode` as private (keep for history)

### Stage 4 — Cleanup
1. Update Obsidian vault project card to reference `claude-harness`
2. Update any QMD collections that index `lazy-claudecode` to point to `claude-harness`
3. Update MEMORY.md references if needed

## What stays in lazy-claudecode (archived, private)

- Full git history of the harness evolution
- Personal profiles (historical — now in chezmoi)
- ADRs with personal context (historical — scrubbed versions in claude-harness)
- Memory pipeline data (JSONL, MEMORY.md)

## Naming

- Public repo: `claude-harness` (or `lcc` if shorter is preferred)
- LaunchAgent prefix: user-chosen during `lcc-admin init` (e.g., `com.lazynet`, `com.myname`)
- QMD collection prefix: user-chosen during init (e.g., `lazy`, `work`)
- Profile names: user-chosen (no defaults beyond "default")

## Out of scope

- Cross-platform LaunchAgent alternatives (systemd, cron) — future work
- GUI for profile management
- Auto-detection of vault/knowledge base path
- Plugin system for skills — skills are just directories with SKILL.md, no registry needed
