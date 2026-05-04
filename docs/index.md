# lazy-harness

A cross-platform harnessing framework for AI coding agents.

`lazy-harness` turns a raw AI coding agent (Claude Code today, others planned) into a daily-driver workstation by adding the scaffolding that agents do not ship with: multi-profile isolation, a hook engine, a monitoring pipeline, a knowledge directory, a scheduler, and a session memory model that persists across conversations.

## What it gives you

- **Profiles.** Isolate separate agent setups — personal, work, client, experimental — with their own `CLAUDE.md`, `settings.json`, skills, and knowledge. Switch by directory or env var.
- **Hooks.** A cross-platform hook engine with built-in hooks for session-start context injection, pre-compact summaries, post-compact context re-injection, session export, and compound loop enforcement. Bring your own hooks via config.
- **Monitoring.** SQLite-backed metrics on every session: duration, message count, tools used, cost. Nine built-in `lh status` views.
- **Knowledge.** A filesystem knowledge directory for sessions and distilled learnings, optionally indexed by [QMD](https://github.com/tobi/qmd) for semantic search.
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
