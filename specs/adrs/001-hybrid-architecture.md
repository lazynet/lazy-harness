# ADR-001: Hybrid architecture — framework code + dotfile config

**Status:** accepted
**Date:** 2026-04-12

## Context

`lazy-harness` has two kinds of content with fundamentally different ownership:

1. **Framework code** — the CLI, hook engine, deploy engine, migration engine, selftest runner. Written once, shipped to everyone, upgraded independently of any user's setup. Belongs to the project.
2. **Personal harness content** — the actual `CLAUDE.md` instructing the agent, the specific hooks a user wants enabled, the profiles they separate work from personal, the skills they write. Belongs to the user, not to the project.

A framework that mixes the two either forces every user to fork (and every fork diverges) or forces the framework to ship someone's opinions as defaults. Both outcomes kill reuse.

## Decision

Split the two along a filesystem boundary:

- **Framework** ships as a Python package installed with `uv tool install`. Its only runtime surface on disk is the `lh` executable plus whatever `uv` puts under `~/.local/share/uv/tools/lazy-harness/`. Upgrades are `uv tool upgrade lazy-harness` and nothing else.
- **Personal content** lives under `~/.config/lazy-harness/` — `config.toml`, `profiles/<name>/*`, `hooks/*.py`. The directory is owned by the user, versioned with their dotfiles (chezmoi, stow, yadm, plain git — the framework does not care), and survives `uv tool uninstall`.

The framework **reads from** that directory but never writes to it outside explicit commands like `lh init` and `lh migrate`. The deploy engine (`src/lazy_harness/deploy/`) bridges the two by symlinking `~/.config/lazy-harness/profiles/<name>/` into the agent's expected config dir (`~/.claude-<name>/` for Claude Code) — see [ADR-009](009-profile-symlink-deploy.md).

## Alternatives considered

- **Monorepo (framework + personal content in the same repo).** Tested in the predecessor project. Every improvement tangled with personal config; sharing required untangling; the boundary never stabilized.
- **Template repo (fork-and-customize).** Forks go stale immediately. Upstream fixes arrive as manual cherry-picks. After three months nobody upgrades.
- **Installer-only, no persistent framework.** Curl-bash script that drops files and exits. No upgrade path, no shared hook library, no recourse when something breaks — each user owns their own copy of the bug.
- **Framework ships its own "default" profile bundled.** Would make `lh init` feel faster, but bakes one person's opinions into a public tool. Rejected.

## Consequences

- Users need no repo to try the framework — `lh init` scaffolds a minimal `~/.config/lazy-harness/` on first run.
- Power users version `~/.config/lazy-harness/` however they like. The framework is intentionally unopinionated about the dotfile manager.
- Framework upgrades are independent and reversible (`uv tool upgrade` / `uv tool install lazy-harness==X.Y.Z`).
- Every feature must pick a side: does this belong in the package, or in `~/.config/lazy-harness/`? If the answer is "it depends on the user", it goes in the config dir.
- The public docs site never assumes a specific personal setup. The user-facing surface is what the framework itself does; profiles are examples, not product.
