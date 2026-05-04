# Installing lazy-harness

## Prerequisites

- **Python 3.11 or later.** Check with `python3 --version`.
- **[uv](https://docs.astral.sh/uv/).** The Python package manager used to install lazy-harness. Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Claude Code** (the agent lazy-harness wraps). Install from [claude.com/claude-code](https://claude.com/claude-code).
- **git** (for the install step — lazy-harness is not on PyPI yet).
- Optional: [QMD](https://github.com/tobi/qmd) for semantic search across your knowledge directory.

## Platforms

- macOS 13+ (Apple Silicon and Intel)
- Linux (tested on Arch, Debian, Ubuntu)
- Windows: not supported yet

## Install

```bash
uv tool install git+https://github.com/lazynet/lazy-harness
```

This installs the `lh` binary into `~/.local/bin/lh` (or wherever your `uv` prefix is). Verify:

```bash
lh --version
lh doctor
```

`lh doctor` checks your system prerequisites. Expected output: all green.

## Choose your path

Two entry points depending on what is already on your machine:

### If you do NOT have an existing Claude Code setup

```bash
lh init
```

This runs an interactive wizard that creates `~/.config/lazy-harness/config.toml`, a default profile, and your knowledge directory. See [first run](first-run.md) for details.

`lh init` refuses to run on a system with existing Claude Code state. This is deliberate — it protects your data.

### If you DO have an existing Claude Code setup

```bash
lh migrate --dry-run
```

This scans your system, detects what exists (profiles, symlinks, LaunchAgents, QMD collections, knowledge directories), and prints a migration plan. Review the plan. Then:

```bash
lh migrate
```

Execution requires a recent (< 1 hour) dry-run. Migration takes a full backup first and supports `lh migrate --rollback`. See the [migrating guide](migrating.md) for the full flow.

## Upgrading

```bash
uv tool upgrade lazy-harness
```

## Uninstalling

```bash
uv tool uninstall lazy-harness
```

This removes the `lh` binary but leaves your config, profiles, knowledge directory, and data intact. To fully purge:

```bash
rm -rf ~/.config/lazy-harness ~/.local/share/lazy-harness ~/.cache/lazy-harness
```

Note: this does NOT remove your agent's config (`~/.claude/` or `~/.claude-<profile>/`). Those remain intact — lazy-harness never owns them, it only deploys into them.
