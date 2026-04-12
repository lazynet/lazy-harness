# ADR-001: Hybrid Architecture (Framework + Dotfile Config)

**Status:** accepted
**Date:** 2026-04-12

## Context

lazy-harness needs to be both a reusable product and personally customizable. The user's profiles, skills, and agent instructions are personal content that shouldn't live in the framework repo.

## Decision

Framework installs as a Python package. User config lives in `~/.config/lazy-harness/` as standard dotfiles, managed by whatever dotfile tool the user prefers (chezmoi, stow, etc.).

## Alternatives Considered

- **Monorepo (framework + content):** Coupling, can't share framework without sharing personal config.
- **Template repo (fork & customize):** Updates are manual cherry-picks. Diverges fast.
- **Installer-only (no persistent framework):** No upgrade path, no shared hooks/skills.

## Consequences

- Users need no repo to use the framework — `lh init` is enough.
- Power users can version their `~/.config/lazy-harness/` with git or chezmoi.
- Framework updates are independent of user config (`uv tool upgrade`).
