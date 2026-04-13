# lcc-status: Migration from Bash to Python + Rich

> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.


**Date:** 2026-04-04
**Status:** Approved
**Scope:** Full rewrite of `scripts/monitoring/lcc-status` from bash to Python using `rich` for TUI rendering.

## Problem

The current bash implementation uses `printf` with hardcoded column widths. When data exceeds expected lengths (long project names, model IDs), columns overlap and the table becomes unreadable. The jq pipelines for data aggregation are complex and fragile.

## Decision

Migrate all of `lcc-status` to Python with `rich` as the rendering library. This is the first step toward migrating all of `lcc-admin` output to Python for consistency.

## Architecture

```
scripts/monitoring/
  lcc-status              # Python entry point: argparse + dispatch
  _lcc_common.py          # Data layer: profiles, pricing, formatting, stats
  _lcc_render.py          # Presentation layer: Rich table/panel builders
  _status-cache.py        # Unchanged (existing cache builder)
  _pricing.sh             # Kept for backward compat with bash callers
```

### Module responsibilities

**`_lcc_common.py`** — Data layer, no rendering logic:
- `load_profiles(config_path)` → list of Profile namedtuples
- `active_profile(profiles)` → detect via ~/.claude symlink
- `load_pricing()` → dict of model rates
- `format_tokens(n)` → "1.2K", "350.7M"
- `time_ago(ts)` → "3h ago", "2d ago"
- `load_stats(period, group_by)` → filter and aggregate JSONL
- `ensure_cache(profiles, rebuild)` → call _status-cache.py
- Constants: CACHE_DIR, STATS_FILE, LOGS_DIR, LCC_CONFIG, QUEUE_DIR

**`_lcc_render.py`** — Presentation layer, no data logic:
- `create_console()` → configured rich.Console
- `status_style(value)` → maps status strings to rich styles
- `make_table(columns, rows, ...)` → rich.Table with right-aligned numerics
- `make_panel(title, items)` → rich.Panel for overview
- `print_section(console, title)` → consistent section headers

**`lcc-status`** — Orchestration:
- argparse with subcommands
- Each view function: get data from _lcc_common, render with _lcc_render
- Shebang: `#!/usr/bin/env python3`

### Sub-views and their data sources

| View | Data source | Rich component |
|------|------------|----------------|
| overview | stats JSONL + hooks.log + launchctl + queue dir | Panel |
| profiles | profiles config + `claude auth status` + settings.json | Table |
| projects | filesystem scan + JSONL mtimes | Table |
| sessions | stats JSONL grouped by date | Table + total row |
| tokens | stats JSONL grouped by project/model/etc | Table + total row |
| hooks | hooks.log parsing | Table + text |
| cron | plist files + launchctl | Table |
| queue | queue dir + compound-loop.log | Table + list |
| memory | decisions.jsonl + failures.jsonl + learnings | Table + list |

## Dependencies

- `rich` — installed via `uv pip install rich`. Hard dependency, no fallback.

## What stays in bash

- `lcc-admin` remains bash (dispatch + interactive commands like init, migrate, move-projects)
- `_lcc-common.sh` stays for bash callers
- `_pricing.sh` stays for backward compat

## Migration path for rest of lcc-admin

Future work. When other `lcc-admin` subcommands get migrated, they import from `_lcc_common.py` and `_lcc_render.py`.
