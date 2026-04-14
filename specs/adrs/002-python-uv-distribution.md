# ADR-002: Python 3.11+ with `uv tool install` as the only distribution channel

**Status:** accepted
**Date:** 2026-04-12

## Context

The framework has to run on macOS, Linux, and Windows; it must be installable without compiling anything; it must be upgradable in one command; and it must let us test every code path cheaply. The predecessor was a blend of Python modules and bash scripts, which worked on one machine but could not survive cross-platform distribution.

We also had existing Python code we did not want to throw away: the monitoring pipeline, the stats views, the config loader. Rewriting in another language meant rewriting tests too.

## Decision

- **Language:** Python 3.11+ for 100% of framework code. No bash shell scripts in the code path, except `set -euo pipefail` one-liners that get called as opaque subprocess from Python if truly unavoidable.
- **Distribution:** `uv tool install git+https://github.com/lazynet/lazy-harness` during development, `uv tool install lazy-harness` once published to PyPI. The tool binary is `lh`, declared in `pyproject.toml` under `[project.scripts]`.
- **Runtime dependencies:** `click`, `tomli-w` (for writing TOML — reading uses stdlib `tomllib`), a few small utilities. No C extensions, no compilation on install, no virtualenv dance — `uv` handles all of that.
- **Minimum Python:** 3.11, because that is the version where `tomllib` is in stdlib. This removes the TOML-parsing dependency and matches the Python baseline of the tools we integrate with.

## Alternatives considered

- **Node / TypeScript.** Claude Code itself is Node, so it would reuse the existing runtime. Rejected because it forces Node on users who do not otherwise need it, and we would lose the existing Python monitoring code. TypeScript's type system is not meaningfully stronger than modern Python type hints for our problem space.
- **Go (single compiled binary).** Zero-dependency installation is attractive, but every line of existing code would have to be rewritten, tests included, with no proportional payoff. Cross-compilation to Windows is also non-trivial.
- **Rust.** Same objection as Go, amplified. We would pay the rewrite cost without shipping any feature the user can see.
- **Keep the bash + Python mix.** Fast to extend if you are already the author on macOS. Hostile to Windows. Hard to test (bash scripts need bats or a fake shell environment). Two languages to review every PR. Rejected.

## Consequences

- `uv` is the only prerequisite for installing `lazy-harness`. Users without `uv` get a one-line install step (documented in the getting-started pages) and are then set for everything.
- 100% of code is pytest-testable with no shell gymnastics. The test suite mirrors `src/lazy_harness/` one-to-one and runs in a few seconds.
- Windows support is realistic (no bash dependency), though today the CI only exercises macOS and Linux. `core/paths.py` already handles Windows path resolution (see [ADR-005](005-xdg-first-paths.md)).
- `tomllib` being stdlib means the TOML read path has zero runtime dependencies — a meaningful guarantee when the config loader is the first thing any `lh` command touches.
- The one-way door: we are committed to Python for this project. If we ever decide to rewrite in Go, it is a new project with a new name.
