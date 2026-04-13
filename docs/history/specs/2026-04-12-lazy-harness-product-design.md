# lazy-harness — Product Design Spec

> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.


**Date:** 2026-04-12
**Status:** approved
**Author:** lazynet

## Summary

Transform lazy-claudecode from a personal Claude Code setup into `lazy-harness`: a generic, cross-platform harnessing framework for AI coding agents. The framework installs as a Python package, stores user config in `~/.config/lazy-harness/` as standard dotfiles, and supports Claude Code as the first agent with an adapter pattern for future agents (Copilot, Ollama, Cursor, etc.).

## Goals

1. **Zero hard coupling** to any personal setup — no hardcoded paths, usernames, or tool-specific assumptions.
2. **Installable from scratch** with a CLI wizard (`lh init`).
3. **Cross-platform** — macOS, Linux, Windows.
4. **Observable** — metrics, costs, session tracking with dashboard and export.
5. **Extensible** — hooks, plugins, agent adapters, built-in skills.
6. **Self-documenting** — skills that teach the user how to configure, extend, and operate the harness.

## Non-goals (v1)

- Agent adapters beyond Claude Code.
- Web UI for monitoring (CLI dashboard is sufficient).
- Publishing to PyPI (install from git clone initially).
- Windows support in v1 (macOS + Linux first, Windows as fast follow).

---

## Architecture

### Two concerns, cleanly separated

| Concern | Where it lives | Who owns it |
|---|---|---|
| Framework (code) | `lazy-harness` Python package | The project |
| User config (content) | `~/.config/lazy-harness/` | Each user |

There is no "instance repo". User config is a dotfile directory, versionable with chezmoi or any dotfile manager. The user's profiles, skills, docs, and routers live here.

### Directory structure — Framework

```
lazy-harness/
├── pyproject.toml
├── src/lazy_harness/
│   ├── __init__.py
│   ├── cli/                  # CLI entrypoint: `lh`
│   │   ├── __init__.py
│   │   ├── main.py           # top-level CLI dispatcher
│   │   ├── init.py           # `lh init` wizard
│   │   ├── profile.py        # `lh profile *`
│   │   ├── deploy.py         # `lh deploy`
│   │   ├── hooks.py          # `lh hooks *`
│   │   ├── status.py         # `lh status *`
│   │   ├── knowledge.py      # `lh knowledge *`
│   │   ├── scheduler.py      # `lh scheduler *`
│   │   └── selftest.py       # `lh selftest`
│   ├── core/
│   │   ├── config.py         # TOML config loading & validation
│   │   ├── profiles.py       # Profile management
│   │   └── paths.py          # Cross-platform path resolution
│   ├── agents/
│   │   ├── base.py           # Agent protocol/ABC
│   │   ├── claude_code.py    # Claude Code adapter
│   │   └── registry.py       # Agent discovery from config
│   ├── hooks/
│   │   ├── engine.py         # Hook resolution & execution
│   │   ├── builtins/         # Built-in hook scripts
│   │   │   ├── context_inject.py
│   │   │   ├── session_export.py
│   │   │   ├── learnings_eval.py
│   │   │   └── pre_compact.py
│   │   └── loader.py         # Discover user + plugin hooks
│   ├── monitoring/
│   │   ├── collector.py      # Stats collection from agent sessions
│   │   ├── db.py             # SQLite metrics store
│   │   ├── pricing.py        # Model pricing (built-in + overrides + remote update)
│   │   ├── dashboard.py      # Rich TUI dashboard
│   │   └── export.py         # CSV/JSON export
│   ├── knowledge/
│   │   ├── directory.py      # Knowledge dir management
│   │   ├── qmd.py            # QMD integration
│   │   └── exporters.py      # Session → markdown, learnings pipeline
│   ├── scheduler/
│   │   ├── base.py           # Scheduler ABC
│   │   ├── launchd.py        # macOS LaunchAgents
│   │   ├── systemd.py        # Linux systemd timers
│   │   ├── cron.py           # Fallback cron
│   │   └── manager.py        # Auto-detect & dispatch
│   └── skills/
│       ├── lh_setup/         # Guide agent through setup
│       ├── lh_doctor/        # Diagnose + suggest fixes
│       ├── lh_extend/        # Guide hook/plugin/adapter creation
│       ├── lh_status/        # Interpret metrics, suggest optimizations
│       └── lh_onboard/       # Educate user about the harness
├── templates/
│   ├── config.toml.j2        # Default config template
│   ├── profile/              # Profile skeleton (CLAUDE.md, settings.json)
│   └── hooks/                # Example custom hook
├── docs/
│   ├── quickstart.md
│   ├── config-reference.md
│   ├── cli-reference.md
│   ├── guides/
│   │   ├── add-profile.md
│   │   ├── configure-qmd.md
│   │   ├── create-hook.md
│   │   └── enable-monitoring.md
│   ├── architecture/
│   │   ├── overview.md
│   │   └── adrs/             # Architecture Decision Records
│   └── extending/
│       ├── agent-adapters.md
│       ├── hook-authoring.md
│       └── plugin-api.md
└── tests/
    ├── unit/
    ├── integration/
    └── conftest.py
```

### Directory structure — User config

```
~/.config/lazy-harness/
├── config.toml               # Central config
├── profiles/
│   ├── personal/
│   │   ├── CLAUDE.md         # Agent instructions for this profile
│   │   ├── settings.json     # Agent settings
│   │   ├── docs/             # Progressive disclosure docs
│   │   ├── skills/           # Profile-specific skills
│   │   └── commands/         # Slash commands
│   └── work/
│       └── ...
├── routers/                  # Workspace routers (optional)
├── hooks/                    # User custom hooks
├── knowledge/                # Knowledge engine config
│   └── collections.toml      # QMD collection definitions
└── plugins/                  # Plugin configs
```

---

## Config format

Central config at `~/.config/lazy-harness/config.toml`:

```toml
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "personal"

[profiles.personal]
config_dir = "~/.claude-personal"
roots = ["~/projects", "~"]

[profiles.work]
config_dir = "~/.claude-work"
roots = ["~/work"]

[knowledge]
path = "~/Documents/my-knowledge"

[knowledge.sessions]
enabled = true
subdir = "sessions"

[knowledge.learnings]
enabled = true
subdir = "learnings"

[knowledge.search]
engine = "qmd"

[hooks.session_start]
scripts = ["context-inject", "git-status"]

[hooks.session_stop]
scripts = ["session-export", "learnings-eval"]

[hooks.pre_compact]
scripts = ["context-reinject"]

[monitoring]
enabled = true
db = "~/.local/share/lazy-harness/metrics.db"

[monitoring.pricing]
"claude-opus-4-6" = { input = 15.0, output = 75.0, cache_read = 1.5, cache_create = 18.75 }

[monitoring.alerts]
daily_budget = 50.0

[scheduler]
backend = "auto"

[scheduler.jobs.qmd_sync]
schedule = "*/30 * * * *"
command = "lh knowledge sync"

[scheduler.jobs.qmd_embed]
schedule = "0 * * * *"
command = "lh knowledge embed"
```

---

## Agent Abstraction

```python
# agents/base.py
from typing import Protocol

class AgentAdapter(Protocol):
    name: str

    def config_dir(self, profile_name: str) -> Path:
        """Where this agent stores profile config."""
        ...

    def parse_session(self, path: Path) -> Session:
        """Parse a session file into a Session object."""
        ...

    def supported_hooks(self) -> list[HookEvent]:
        """Which hook events this agent supports."""
        ...

    def generate_hook_config(self, hooks: dict[HookEvent, list[Hook]]) -> dict:
        """Generate agent-native hook config (e.g., settings.json for Claude Code)."""
        ...

    def session_files(self, profile: Profile) -> list[Path]:
        """Find session files for a profile."""
        ...
```

v1 implements only `claude_code.py`. Adding a new agent = implementing this protocol.

---

## Hook Engine

Hooks are resolved in order:
1. **Built-in** hooks (shipped with lazy-harness)
2. **User hooks** (in `~/.config/lazy-harness/hooks/`)
3. **Plugin hooks** (registered by plugins)

Hook scripts can be Python functions or shell scripts. The engine:
- Receives event + payload from the agent adapter
- Resolves which hooks to run and in what order
- Executes them sequentially, logs results
- Reports failures without blocking the agent (exit 0 always)

The agent adapter generates native config (e.g., `settings.json` for Claude Code) that points to the framework's hook dispatcher.

---

## Knowledge & QMD

The framework manages a **knowledge directory** — a flat directory of markdown files. It can be an Obsidian vault, a plain directory, or anything that produces `.md` files.

QMD is a required dependency for search. The framework:
- Validates QMD is installed and responsive (`lh doctor`)
- Manages collection configuration
- Provides `lh knowledge sync` and `lh knowledge embed` commands
- Exposes search via built-in hooks (context injection)

Session export and learnings pipelines write to the knowledge directory. QMD indexes from there.

---

## Monitoring

**Data flow:**
```
Agent sessions (JSONL) → Stats collector → SQLite → Dashboard / Export
```

**SQLite schema (core tables):**
- `sessions` — id, profile, agent, start, end, tokens_in, tokens_out, cache_read, cache_create, model, cost_usd
- `hook_runs` — id, session_id, hook_name, event, duration_ms, exit_code, error
- `daily_aggregates` — materialized view for fast dashboard queries

**Pricing:**
- Built-in defaults for known models
- User overrides in config.toml
- `lh status pricing update` to fetch latest from API (future)

---

## Built-in Skills

Skills are markdown files that agents can invoke to self-manage the harness.

| Skill | Purpose |
|---|---|
| `lh-setup` | Guide agent through initial setup or adding a component |
| `lh-doctor` | Run diagnostics, interpret results, suggest fixes |
| `lh-extend` | Guide hook/plugin/adapter creation |
| `lh-status` | Interpret metrics and costs, suggest optimizations |
| `lh-onboard` | Educate user about what the harness is and how it works |

Skills are deployed to the active agent's skill directory via `lh deploy`. They are agent-agnostic in content (markdown instructions) but placed where each agent expects them.

---

## CLI Reference

```
lh init                          # Interactive setup wizard
lh doctor                        # Health check
lh selftest                      # Smoke tests on current install

lh profile list                  # Show profiles and status
lh profile add <name>            # Create new profile with skeleton
lh profile remove <name>         # Remove profile

lh deploy                        # Full deploy (symlinks, hooks, skills, scheduler)
lh deploy hooks                  # Deploy only hooks
lh deploy skills                 # Deploy only skills
lh deploy scheduler              # Deploy only scheduled jobs

lh hooks list                    # Show registered hooks by event
lh hooks run <event>             # Execute hooks for event (debug)

lh status                        # Dashboard overview
lh status costs [--period 7d]    # Cost breakdown
lh status sessions               # Recent sessions
lh status export --format csv    # Export metrics

lh knowledge sync                # Sync QMD collections
lh knowledge embed               # Run QMD embedding
lh knowledge search <query>      # Search knowledge base

lh scheduler install              # Register scheduled jobs for current OS
lh scheduler status               # Show job status
lh scheduler uninstall            # Remove scheduled jobs

lh plugin list                   # Show available plugins
lh plugin enable <name>          # Enable a plugin
lh plugin disable <name>         # Disable a plugin
```

---

## Testing Strategy

### Three levels

**Unit tests** — pure logic, no side effects:
- Config parsing (TOML → dataclasses)
- Agent adapter logic (session parsing, token counting)
- Hook resolution (ordering, filtering)
- Cost calculation
- Path resolution (cross-platform)

**Integration tests** — real filesystem (tmp dirs):
- `lh init` generates correct structure
- `lh deploy` creates valid symlinks
- `lh profile add/remove` modifies config and directories
- Hook engine executes scripts and captures output
- Scheduler generates correct config per backend
- Knowledge dir export writes correctly

**Smoke tests** — end-to-end install validation:
- `uv tool install . && lh init && lh doctor` passes
- CI matrix: macOS + Ubuntu (Windows deferred)
- `lh selftest` runs smoke tests on current installation

### Tooling

- `pytest` with real temporary directories (no filesystem mocks)
- GitHub Actions CI with macOS + Ubuntu matrix
- Each new module ships with tests — no merge without happy path coverage

---

## Documentation Strategy

Three audiences, three layers:

**User docs** (`docs/`):
- Quickstart — zero to working harness in 5 minutes
- Config reference — every `config.toml` key documented
- CLI reference — every command with examples
- Guides — task-oriented walkthroughs

**Architecture docs** (`docs/architecture/`):
- ADRs — every design decision with context, alternatives, consequences
- Design overview — component diagram, data flow

**Extension docs** (`docs/extending/`):
- Agent adapter guide
- Hook authoring guide
- Plugin API (when it exists)

Format: plain markdown in repo. No static site generator until there's an audience.

Rule: every feature merges with its corresponding doc.

---

## Migration Path

### Phase 1 — Framework Bootstrap
- Create `lazy-harness` repo with `pyproject.toml`, `src/lazy_harness/`, tests
- Implement core: TOML config, profile management, basic CLI (`lh init`, `lh profile`, `lh doctor`)
- Migrate monitoring Python code to framework
- **Exit criteria:** `lh init && lh doctor` works

### Phase 2 — Hooks and Deploy
- Migrate hook engine from bash to Python
- Migrate `deploy.sh` → `lh deploy`
- Migrate scheduler (LaunchAgents → cross-platform abstraction)
- **Exit criteria:** `lh deploy` replaces `deploy.sh`, hooks work via framework

### Phase 3 — Knowledge and QMD
- Migrate session export and learnings pipeline
- QMD integration as framework module
- **Exit criteria:** `lh knowledge sync`, `lh knowledge embed` work

### Phase 4 — Cutover
- Move personal content from `lazy-claudecode/` to `~/.config/lazy-harness/`
- Archive `lazy-claudecode` repo
- chezmoi manages `~/.config/lazy-harness/`
- **Exit criteria:** `lazy-claudecode` fully replaced, `lh selftest` passes

**Migration rule:** the old system keeps working at every phase. Nothing is shut down until its replacement is validated with `lh selftest` and at least one week of real use.

---

## Design Decisions

Documented as ADRs in `docs/architecture/adrs/`. Decisions made during this design:

1. **ADR-001: Hybrid architecture (framework + dotfile config)** — Framework as installable package, user config as standard dotfiles in `~/.config/lazy-harness/`. Rejected: monorepo, template repo, installer-only.
2. **ADR-002: Python with uv distribution** — Python for CLI and all tooling. Distribution via `uv tool install` (git clone initially, PyPI later). Rejected: Node/TypeScript, Go.
3. **ADR-003: TOML config format** — Single `config.toml` for all framework config. Built-in `tomllib` (Python 3.11+). Rejected: YAML (needs dependency, footguns), JSON (no comments).
4. **ADR-004: Agent adapter pattern** — Protocol-based abstraction for agent support. Only Claude Code in v1. Rejected: agent-specific code throughout, plugin-only agents.
5. **ADR-005: SQLite for metrics** — Replace JSONL stats cache with SQLite for queries and aggregation. Rejected: keep JSONL (doesn't scale), PostgreSQL (overkill).
6. **ADR-006: Cross-platform scheduler abstraction** — Auto-detect launchd/systemd/cron. Rejected: launchd-only (not cross-platform), external scheduler dependency.
7. **ADR-007: Parallel bootstrap migration** — New repo alongside old, migrate piece by piece. Old system works until cutover validated. Rejected: big bang rewrite, in-place migration.
8. **ADR-008: Built-in skills for self-management** — Framework ships with skills that agents use to configure, diagnose, extend, and explain the harness. Rejected: CLI-only management, external docs only.
9. **ADR-009: No instance repo** — User config lives in `~/.config/lazy-harness/`, managed as dotfiles. No separate instance repo required. Rejected: mandatory instance repo, config embedded in framework.
