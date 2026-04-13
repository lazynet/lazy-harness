# lazy-harness

[![Docs](https://img.shields.io/badge/docs-lazynet.github.io-blue)](https://lazynet.github.io/lazy-harness/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](#license)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Platform: macOS | Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#platforms)

A cross-platform harnessing framework for AI coding agents.

`lazy-harness` turns a raw AI coding agent (Claude Code today, others planned) into a daily-driver workstation by adding the scaffolding that agents do not ship with: multi-profile isolation, a cross-platform hook engine, a monitoring pipeline, a knowledge directory, a unified scheduler, and a session memory model that persists across conversations.

Full documentation: **https://lazynet.github.io/lazy-harness/**

## What it gives you

- **Profiles.** Isolate separate agent setups — personal, work, client, experimental — each with its own `CLAUDE.md`, `settings.json`, skills, and knowledge. Switch by directory or env var.
- **Hooks.** A cross-platform hook engine with built-ins for session-start context injection, pre-compact summaries, session export, and compound-loop enforcement. Bring your own hooks via `config.toml`.
- **Monitoring.** SQLite-backed metrics on every session: duration, message count, tools used, cost. Nine built-in `lh status` views.
- **Knowledge.** A filesystem knowledge directory for sessions and distilled learnings, optionally indexed by [QMD](https://github.com/lazynet/qmd) for semantic search.
- **Scheduler.** A unified interface over launchd, systemd, and cron. Declare recurring jobs in `config.toml`; `lh scheduler install` does the rest.
- **Migration.** `lh migrate` takes an existing Claude Code setup and converts it into a lazy-harness installation with a dry-run gate, full backup, and rollback.

## Quick start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [Claude Code](https://claude.com/claude-code) — the agent being wrapped
- git

### Install

```bash
uv tool install git+https://github.com/lazynet/lazy-harness
lh --version
lh doctor
```

### First run

Two entry points depending on what's already on your machine:

```bash
# New install (no existing Claude Code state)
lh init

# Existing Claude Code setup — always dry-run first
lh migrate --dry-run
lh migrate
```

`lh init` refuses to run when existing Claude Code state is present. `lh migrate` requires a recent dry-run before it will touch anything, takes a full backup, and supports `lh migrate --rollback`.

See the [getting-started guide](https://lazynet.github.io/lazy-harness/getting-started/install/) for the full flow.

## Platforms

- macOS 13+ (Apple Silicon and Intel)
- Linux (tested on Arch, Debian, Ubuntu)
- Windows: not supported yet

Supported agent: **Claude Code**. Other agents are planned via the adapter layer (see [ADR-004](https://lazynet.github.io/lazy-harness/architecture/adrs/004-agent-adapter-pattern/)).

## Documentation

The full docs site is published from `docs/` via MkDocs Material and GitHub Pages on every push to `main`:

- [The problem it solves](https://lazynet.github.io/lazy-harness/why/problem/)
- [Philosophy](https://lazynet.github.io/lazy-harness/why/philosophy/)
- [Memory model](https://lazynet.github.io/lazy-harness/why/memory-model/)
- [Getting started](https://lazynet.github.io/lazy-harness/getting-started/install/)
- [CLI reference](https://lazynet.github.io/lazy-harness/reference/cli/)
- [Config reference](https://lazynet.github.io/lazy-harness/reference/config/)
- [Architecture overview](https://lazynet.github.io/lazy-harness/architecture/overview/)

## Status

`lazy-harness` is the actively developed line. It currently targets Claude Code and runs on macOS and Linux.

## Contributing

Issues and PRs welcome at [github.com/lazynet/lazy-harness](https://github.com/lazynet/lazy-harness). For non-trivial changes, please open an issue first to discuss scope.

Local development:

```bash
git clone https://github.com/lazynet/lazy-harness
cd lazy-harness
uv sync
uv run pytest
```

## License

MIT — see [`pyproject.toml`](pyproject.toml).
