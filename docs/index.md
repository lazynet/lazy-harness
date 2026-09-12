# lazy-harness

A cross-platform harnessing framework for AI coding agents.

`lazy-harness` turns a raw AI coding agent (Claude Code today, others planned) into a daily-driver workstation by adding the scaffolding that agents do not ship with: multi-profile isolation, a hook engine, a monitoring pipeline, a knowledge directory, a scheduler, and a session memory model that persists across conversations.

## What it gives you

- **Profiles.** Isolate separate agent setups — personal, work, client, experimental — with their own `CLAUDE.md`, `settings.json`, skills, and knowledge. Switch by directory or env var.
- **Hooks.** A cross-platform hook engine with built-ins across seven events: session-start context injection and preflight checks, pre-compact summaries, session export, compound-loop distillation on both `Stop` and `SessionEnd`, deterministic Engram mirroring, a context-rotation notice, post-edit auto-format, `CLAUDE.md` re-composition, and four `PreToolUse` gates — two that block (destructive commands, unsafe shared-stash git operations) and two that warn (oversized `MEMORY.md` writes, unbounded reads of large files). Bring your own hooks via config. Every one of them is documented in [how hooks work](how/hooks.md), held to the code by a coherence test in both directions.
- **Guardrails.** A built-in `PreToolUse` security hook blocks high-blast-radius shell commands (recursive deletes, `git reset --hard`, `terraform destroy`, `DROP TABLE`) and any file tool reaching a secret path (`.env`, SSH keys, `.aws/`, `*.pem`) before the agent executes them. Shell rules are overridable per profile via `[hooks.pre_tool_use].allow_patterns`; the secret-path globs deliberately are not. See [how hooks work](how/hooks.md#pre-tool-use-security-runs-on-pretooluse).
- **Monitoring.** SQLite-backed metrics on every session: duration, message count, tools used, cost. Ten built-in `lh status` views, a pluggable sink layer (`sqlite_local` always; `http_remote` opt-in for shipping events to a backend with retry + exponential backoff).
- **Knowledge.** A filesystem knowledge store — a git repository holding exported sessions, distilled learnings and each project's memory, synced between machines by a scheduled `lh knowledge push` that never blocks a session — plus auto-orchestration of three best-of-breed memory tools when installed: [QMD](https://github.com/tobi/qmd) for searchable semantic recall, [Engram](https://github.com/Gentleman-Programming/engram) for raw episodic memory, and [Graphify](https://github.com/safishamsi/graphify) for code-structure queries. See the [memory model](why/memory-model.md) for the full five-layer picture.
- **Scheduler.** Declare recurring jobs in `config.toml` and `lh scheduler install` writes the native unit files — launchd plists on macOS, systemd user timers on Linux, a delimited crontab block where neither is available. An expression a backend cannot express faithfully aborts the install rather than being approximated.
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

Released continuously from `main` on the 0.x line; every version is cut by release-please, so the [releases page](https://github.com/lazynet/lazy-harness/releases) is the authority on what is current. Supported platforms: macOS, Linux (Windows is not supported). Supported agent: Claude Code — others are planned via the adapter layer ([ADR-004](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/004-agent-adapter-pattern.md)), and none ship yet.
