# ADR-003: TOML Config Format

**Status:** accepted
**Date:** 2026-04-12

## Context

The framework needs a single config file that users edit manually. It must support comments, nested sections, and be parseable without external dependencies.

## Decision

TOML at `~/.config/lazy-harness/config.toml`. Read with `tomllib` (stdlib), write with `tomli-w`.

## Alternatives Considered

- **YAML:** Needs PyYAML dependency. Footguns (Norway problem, implicit typing).
- **JSON:** No comments. Hostile for human-edited config.
- **INI:** No nested structures. Insufficient for profiles + hooks + monitoring config.

## Consequences

- No parsing dependency (tomllib is stdlib in 3.11+).
- One small write dependency (tomli-w) for `lh init` and config updates.
- Consistent with Python ecosystem tooling (pyproject.toml, ruff, uv).
