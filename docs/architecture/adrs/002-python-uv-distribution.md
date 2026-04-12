# ADR-002: Python with uv Distribution

**Status:** accepted
**Date:** 2026-04-12

## Context

The CLI needs to work on macOS, Linux, and Windows. The existing codebase has significant Python code (monitoring, stats) and bash scripts (hooks, deploy).

## Decision

Python 3.11+ for all framework code. Distribution via `uv tool install` (git clone initially, PyPI when stable). Bash scripts are rewritten in Python.

## Alternatives Considered

- **Node/TypeScript:** Claude Code is Node, but requiring Node as a dependency adds friction for non-JS users.
- **Go:** Zero-dependency binary, but higher development cost and no reuse of existing Python code.
- **Keep bash + Python mix:** Not cross-platform (Windows), harder to test, two languages to maintain.

## Consequences

- `uv` is the only prerequisite for installation.
- All code is testable with pytest.
- Windows support is feasible (no bash dependency).
- `tomllib` is built-in from Python 3.11 (no TOML parsing dependency).
