# lazy-harness

[![Docs](https://img.shields.io/badge/docs-lazynet.github.io-blue)](https://lazynet.github.io/lazy-harness/)
[![PyPI compatible](https://img.shields.io/badge/install-uv%20tool-blueviolet)](#install)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](#license)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Platform: macOS | Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](#status)

> **Stop re-explaining your project to your AI agent every morning.**

`lazy-harness` is the missing scaffolding around AI coding agents like [Claude Code](https://claude.com/claude-code): persistent memory across sessions, isolated profiles for personal/work/client setups, a cross-platform hook engine, SQLite-backed monitoring, a knowledge directory, and a unified scheduler — all driven by one TOML file.

It does not fork or proxy the agent. It wraps the environment around it.

Full docs: **https://lazynet.github.io/lazy-harness/**

<details>
<summary><b>Table of contents</b></summary>

- [Why](#why)
- [Features](#features)
- [The memory problem (and how it's solved)](#the-memory-problem-and-how-its-solved)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Is this for you?](#is-this-for-you)
- [Documentation](#documentation)
- [Status](#status)
- [Contributing](#contributing)
- [License](#license)

</details>

## Why

AI coding agents ship as a chat interface and a file tool. That's enough for a demo. It's not enough for 8 hours a day across three projects. You hit predictable walls:

- **Session amnesia.** Every conversation starts from zero. You re-paste the same context every morning.
- **One global config.** Personal experiments, employer code, client work and side projects all share `~/.claude/`. There is no clean switch.
- **No observability.** What did last week cost? Which sessions touched the repo? You can't say.
- **Knowledge is write-only.** What you learn in a session dies when the window closes.
- **Recurring jobs are yours to build.** Pre-compact summaries, weekly reviews, nightly re-indexes — you write the cron entries per platform, by hand.

`lazy-harness` is the scripts, the schedulers and the discipline, packaged as a Python tool.

## Features

| Feature | What it does | Try it |
|---|---|---|
| **Profiles** | Isolate `personal`, `work`, `client` — each with its own `CLAUDE.md`, `settings.json`, skills and knowledge. Switch by directory or env var. | `lh profile add work --config-dir ~/.claude-work --roots ~/repos/work` |
| **Hooks** | Cross-platform hook engine with built-ins for session-start context injection, pre-compact summaries, session export and compound-loop enforcement. Bring your own via `config.toml`. | `lh hooks list` |
| **Monitoring** | SQLite-backed metrics on every session — duration, tokens, tools, cost. Ten built-in dashboard views. | `lh status sessions --period week` |
| **Knowledge** | Filesystem knowledge directory for sessions and distilled learnings, optionally indexed by [QMD](https://github.com/lazynet/qmd) for semantic search. | `lh knowledge sync && lh knowledge embed` |
| **Scheduler** | One interface over launchd, systemd and cron. Declare jobs in TOML; the harness writes the native unit files. | `lh scheduler install` |
| **Migration** | Take an existing Claude Code setup and convert it in place — dry-run gate, full backup, one-command rollback. | `lh migrate --dry-run` |

A typical `~/.config/lazy-harness/config.toml` is small:

```toml
[profiles.personal]
config_dir = "~/.claude-personal"
roots = ["~/repos/lazy"]

[profiles.work]
config_dir = "~/.claude-work"
roots = ["~/repos/work"]

[hooks.SessionStart]
context-inject = { enabled = true }

[hooks.PreCompact]
summarize = { enabled = true }

[scheduler.jobs.metrics-ingest]
schedule = "*/15 * * * *"
command = "lh metrics ingest"
```

## The memory problem (and how it's solved)

The single feature most users notice on day one is that the agent stops forgetting. `lazy-harness` adds **five memory layers** on top of the agent's built-in `CLAUDE.md`, arranged across three time scales:

| Scale | What it answers | Mechanism |
|---|---|---|
| **Short-term** — within a session | "What is this session about right now?" | Session-start context injection + pre-compact summaries |
| **Medium-term** — across sessions in the same project | "What did I decide last time? What broke last month?" | `MEMORY.md` + append-only `decisions.jsonl` / `failures.jsonl` + session export |
| **Long-term** — across all projects | "Where did I see this pattern before?" | Knowledge directory + optional QMD semantic index |

Before `lazy-harness`, the first 5 minutes of every session were context reconstruction. After, they're work. Full breakdown: [Memory model](https://lazynet.github.io/lazy-harness/why/memory-model/).

## Quick start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [Claude Code](https://claude.com/claude-code) — the agent being wrapped
- `git`

### Install

```bash
uv tool install git+https://github.com/lazynet/lazy-harness
lh --version
lh doctor      # verify environment is sane
```

### First run

Pick the entry point that matches your machine:

```bash
# A — Fresh machine, no Claude Code state yet
lh init

# B — Existing Claude Code setup (always dry-run first)
lh migrate --dry-run
lh migrate
```

`lh init` refuses to run when existing Claude Code state is present. `lh migrate` requires a recent dry-run before writing, takes a full backup, and supports `lh migrate --rollback`.

### See it working

```bash
lh selftest                   # end-to-end validation
lh status                     # overview dashboard
lh status sessions --period week
lh hooks list
```

The full walkthrough lives in the [getting-started guide](https://lazynet.github.io/lazy-harness/getting-started/install/).

## How it works

`lazy-harness` keeps a hard boundary between framework code (upgraded with `uv tool upgrade`) and your personal harness content (versioned with your dotfiles). The framework reads from your config and **deploys** it into the agent's directories via symlinks and generated settings — you never edit anything inside the framework package.

```
┌──────────────────────────────┐         ┌─────────────────────────────────┐
│  Framework (Python package)  │         │  User-owned harness content     │
│  installed via uv tool       │         │  ~/.config/lazy-harness/        │
│                              │  reads  │  ├── config.toml                │
│   src/lazy_harness/          │  ────►  │  ├── profiles/                  │
│     cli/  core/  agents/     │         │  │   ├── personal/              │
│     hooks/  knowledge/       │         │  │   │   ├── CLAUDE.md          │
│     monitoring/  scheduler/  │         │  │   │   ├── skills/            │
│     migrate/  selftest/      │         │  │   │   └── settings.json      │
│     init/  deploy/           │         │  │   └── work/                  │
│                              │         │  └── hooks/  (user hooks, opt)  │
└──────────────────────────────┘         └─────────────────────────────────┘
                                                          │
                                                          │ lh deploy
                                                          ▼
                                         ┌─────────────────────────────────┐
                                         │  Agent target dirs (symlinks +  │
                                         │  generated settings)            │
                                         │  ~/.claude-personal/            │
                                         │  ~/.claude-work/                │
                                         │  ~/.claude → default            │
                                         └─────────────────────────────────┘
```

More: [Architecture overview](https://lazynet.github.io/lazy-harness/architecture/overview/) · [ADRs](https://github.com/lazynet/lazy-harness/tree/main/specs/adrs).

## Is this for you?

| You will probably love it if... | You probably do not need it if... |
|---|---|
| You use an AI coding agent for hours a day | You open the agent occasionally to ask a one-off question |
| You juggle multiple repos, employers or clients | You only have one project and one global config |
| You want session metrics and per-project history | You don't care what last week cost |
| You're comfortable in a terminal and editing TOML | You want a GUI |
| You run macOS or Linux | You're on Windows (not supported yet) |

`lazy-harness` is opinionated about *plumbing*, not about *workflow*. Every default is overridable; every feature is opt-in via `config.toml`. It is not a Claude Code fork, not a chat wrapper, not an MCP server.

## Documentation

The full site is built from [`docs/`](docs/) with MkDocs Material and published on every push to `main`:

- [The problem it solves](https://lazynet.github.io/lazy-harness/why/problem/)
- [Philosophy](https://lazynet.github.io/lazy-harness/why/philosophy/)
- [Memory model](https://lazynet.github.io/lazy-harness/why/memory-model/)
- [Getting started](https://lazynet.github.io/lazy-harness/getting-started/install/) · [Migrating from a stock setup](https://lazynet.github.io/lazy-harness/getting-started/migrating/)
- How-tos: [Hooks](https://lazynet.github.io/lazy-harness/how/hooks/) · [Profiles & deploy](https://lazynet.github.io/lazy-harness/how/profiles-and-deploy/) · [Metrics ingest](https://lazynet.github.io/lazy-harness/how/metrics-ingest/) · [Knowledge pipeline](https://lazynet.github.io/lazy-harness/how/knowledge-pipeline/) · [Compound-loop memory](https://lazynet.github.io/lazy-harness/how/memory-compound/)
- Reference: [CLI](https://lazynet.github.io/lazy-harness/reference/cli/) · [Config](https://lazynet.github.io/lazy-harness/reference/config/)
- [Architecture overview](https://lazynet.github.io/lazy-harness/architecture/overview/) · [Roadmap](https://lazynet.github.io/lazy-harness/roadmap/)

## Status

Actively developed. Versioned via [release-please](https://github.com/googleapis/release-please) — see the [changelog](CHANGELOG.md) and [GitHub releases](https://github.com/lazynet/lazy-harness/releases) for what's in each cut.

- **Platforms:** macOS 13+ (Apple Silicon and Intel), Linux (tested on Arch, Debian, Ubuntu).
- **Windows:** not supported yet.
- **Supported agents:** [Claude Code](https://claude.com/claude-code). Other agents are planned via the adapter layer ([ADR-004](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/004-agent-adapter-pattern.md)).

## Contributing

Issues and PRs welcome at [github.com/lazynet/lazy-harness](https://github.com/lazynet/lazy-harness). For non-trivial changes, please open an issue first to discuss scope.

Local development:

```bash
git clone https://github.com/lazynet/lazy-harness
cd lazy-harness
uv sync
uv run pytest
uv run ruff check src tests
uv run --group docs mkdocs build --strict
```

Contributor workflow (worktrees, conventional commits, release flow): [`specs/workflow/`](specs/workflow/) · [`CLAUDE.md`](CLAUDE.md).

## License

MIT — see [`LICENSE`](LICENSE).
