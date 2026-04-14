# QMD Context Gen Redesign

> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.


**Date:** 2026-04-12
**Status:** Approved
**Decision:** Rewrite `qmd-context-gen.sh` to stop owning collection declarations; only regenerate dynamic context portions.

## Problem

`qmd-context-gen.sh` regenerates `~/.config/qmd/index.yml` from scratch every 30 minutes using hardcoded `COLLECTIONS` and `DESCRIPTIONS` dicts. This overwrites any collection added via `qmd collection add`, causing collections to become zombies in the SQLite index (docs exist but `path: null`). Every session that "fixes" QMD gets undone by the next cron run.

Root cause: the script treats `index.yml` as generated output, but users also treat it as mutable config.

## Design

### Principle

`index.yml` is the user's config. `qmd-context-gen.sh` is a maintenance script that enriches it — never overwrites structure.

### Context format with delimiter

Each collection's context has two parts separated by `<!-- auto -->`:

```
Documentación técnica del homelab. <!-- auto --> 34 archivos .md. Contiene: adr, superpowers.
```

- **Before delimiter:** user-written description (fixed, never touched by script)
- **After delimiter:** auto-generated stats (file count, subdirectories)
- If no delimiter exists, the script appends `<!-- auto --> {generated}`
- If no context exists at all, generates `<!-- auto --> {generated}`

### New `qmd-context-gen.sh` behavior

1. Parse `index.yml` — read all collections with their paths, patterns, and contexts
2. For each collection with a valid, existing path:
   - Scan directory: count `.md` files, list subdirs (skip `.git`, `.obsidian`, etc.)
   - Read existing context
   - Split on `<!-- auto -->`, preserve everything before it
   - Regenerate everything after it: `N archivos .md. Contiene: X, Y, Z.`
3. Write updated `index.yml` preserving all collection definitions (paths, patterns, names)
4. Collections with non-existent paths or no path: skip, log warning

### What the script no longer does

- No hardcoded `COLLECTIONS` dict
- No hardcoded `DESCRIPTIONS` dict
- No generating YAML from scratch
- No adding or removing collections

### Zombie cleanup (one-time)

**Purge from SQLite** (orphaned docs, no config):
- `lazy-control-tower`, `LazyMind`, `homelab`, `claude-sessions`
- `supervielle-docs`, `supervielle-iniciativas`, `supervielle-adr`
- `supervielle-mgmt`, `ydi-mgmt`

**Remove from config:**
- `flex-supervielle` (path broken)

**Add with correct paths:**

| Collection | Path |
|---|---|
| `flex-supervielle-mgmt` | `~/repos/flex/mngt/supervielle-mgmt` |
| `flex-mgmt` | `~/repos/flex/mngt/flex-mgmt` |
| `flex-ydi-mgmt` | `~/repos/flex/mngt/ydi-mgmt` |
| `flex-ai-adoption-mgmt` | `~/repos/flex/mngt/ai-adoption-mgmt` |
| `flex-flexigopay-mgmt` | `~/repos/flex/mngt/flexigopay-mgmt` |
| `flex-infra-mgmt` | `~/repos/flex/mngt/infra-mgmt` |
| `flex-urus-mgmt` | `~/repos/flex/mngt/urus-mgmt` |

### Impact on other components

- `qmd-sync.sh`: no changes needed
- `qmd-embed.sh`: no changes needed
- Framework separation: aligns — `index.yml` is personal config, script is framework
- `lcc-admin init`: QMD onboarding flow creates initial collections; `qmd-context-gen.sh` maintains them

## Execution order

1. Rewrite `qmd-context-gen.sh`
2. Clean zombie collections from SQLite
3. Remove `flex-supervielle`, add 7 new collections with correct paths
4. Run `qmd-context-gen.sh` to populate auto contexts
5. Run `qmd embed` for new collections
6. Verify: `qmd status` CLI and MCP show the same collections
