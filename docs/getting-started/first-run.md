# First run

This guide walks through `lh init` from a clean machine. If you are migrating an existing Claude Code setup, see [migrating](migrating.md) instead.

## What `lh init` does

1. Refuses to run if you have existing Claude Code state (`~/.claude/`, `~/.claude-*/`, or an existing `~/.config/lazy-harness/config.toml`).
2. Asks for a profile name (default: `personal`).
3. Asks for the agent (default: `claude-code` — the only option today).
4. Asks for a knowledge directory path (default: `~/Documents/lazy-harness-knowledge`).
5. Detects QMD if present and offers to configure a knowledge collection.
6. Writes `~/.config/lazy-harness/config.toml`.
7. Creates the profile directory at `~/.config/lazy-harness/profiles/<name>/` with a minimal `CLAUDE.md` and `settings.json`.
8. Creates the knowledge directory with `sessions/` and `learnings/` subdirs.

## Running it

```bash
lh init
```

Sample session:

```
lazy-harness — initial setup

Profile name [personal]:
Agent [claude-code]:
Knowledge directory [~/Documents/lazy-harness-knowledge]:
QMD detected. Configure knowledge collection? [Y/n]: Y

✓ Config created at ~/.config/lazy-harness/config.toml
✓ Profile 'personal' created
✓ Knowledge directory ready at ~/Documents/lazy-harness-knowledge
✓ QMD collection configured

Run `lh doctor` to verify your setup.
```

## Verifying

```bash
lh doctor     # system prerequisites
lh selftest   # framework integrity
lh profile ls # list configured profiles
```

All three should exit 0 with green output.

## Starting an agent session

```bash
CLAUDE_CONFIG_DIR=~/.claude-personal claude
```

This launches Claude Code with your personal profile. The `CLAUDE_CONFIG_DIR` env var tells Claude Code to read settings from `~/.claude-personal/` instead of the global `~/.claude/`. You can alias this:

```bash
alias claude-personal='CLAUDE_CONFIG_DIR=~/.claude-personal claude'
```

## Customizing the profile

Your profile lives at `~/.config/lazy-harness/profiles/personal/`. Edit:

- `CLAUDE.md` — the project-level instructions Claude Code will load
- `settings.json` — Claude Code settings (hooks, permissions, etc.)
- `skills/` — custom skills
- `commands/` — custom slash commands

After editing, run `lh profile deploy` to refresh the symlinks into `~/.claude-personal/`.

## Versioning your profile

`lh init` does not version your profile for you. Connect it to your dotfiles manager of choice:

```bash
cd ~/.config/lazy-harness
chezmoi add profiles/
```

(or yadm, or a git submodule, or a plain git repo inside `~/.config/lazy-harness/profiles/`.)

## Next steps

- [Migrating an existing setup](migrating.md) — if you skipped here accidentally
- [CLI reference](../reference/cli.md) — every `lh` subcommand
- [Config reference](../reference/config.md) — every `config.toml` option
