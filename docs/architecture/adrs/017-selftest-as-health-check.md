# ADR-017: Selftest is the framework's user-facing health check, not a test runner

**Status:** accepted
**Date:** 2026-04-13

## Context

The framework has two audiences who need to verify it works, and they need very different things:

- **The developer** running `uv run pytest` wants to confirm the code is correct in isolation, fast, with no dependencies on the user's environment.
- **The user** running `lh selftest` wants to confirm the framework is correct **on their machine** right now: is the config valid, are the profiles deployed, are the hooks wired, is the scheduler backend reachable, is the knowledge directory writable, is the monitoring store accessible?

These are not the same question. A green pytest suite does not prove that the user's `~/.claude-personal/` symlinks resolve. A green selftest does not prove the compound-loop parser handles malformed JSONL. Conflating them — making `lh selftest` run pytest, or making pytest touch the user's real home directory — breaks both.

## Decision

Two independent verification surfaces, sharing no code.

- **`tests/` + pytest.** The code-correctness suite. Hermetic, parameterized on `tmp_path`, run with `uv run pytest`. Mirrors `src/lazy_harness/` one-to-one. Enforced by [ADR-015](015-strict-tdd-workflow.md).
- **`src/lazy_harness/selftest/` — the user-facing health check.** Exposed as `lh selftest`. It is a runner (`selftest/runner.py`) that executes a list of check groups, each living under `selftest/checks/`:
  - `cli_check` — is `lh` resolvable and reporting a coherent version?
  - `config_check` — does `config.toml` exist, parse cleanly, and have the required sections?
  - `profile_check` — is each declared profile's config dir present, and do the symlinks resolve?
  - `hooks_check` — are declared hooks resolvable (builtin or user), and is the agent's native hook config consistent?
  - `scheduler_check` — is the detected scheduler backend reachable, and are declared jobs installed?
  - `knowledge_check` — is the knowledge path writable, are the sessions/learnings subdirs present?
  - `monitoring_check` — does the metrics DB open, does it have the expected schema?

Each check is a `Callable[[], list[CheckResult]]`. A `CheckResult` has a group, name, status (`PASS | WARN | FAIL`), message, and optional fix hint. The runner catches exceptions from each check and converts them to a synthetic `FAILED` result so one broken check cannot take down the whole report.

The runner's job is deliberately tiny: iterate, collect, aggregate. All logic lives in the checks. Adding a new check is one file under `checks/` and one registration in the runner.

## Alternatives considered

- **Make `lh selftest` run pytest against the installed package.** Requires shipping tests, requires a pytest runtime the user may not have, conflates "my machine is wired up correctly" with "the code I installed is internally consistent". Rejected.
- **Unify the two under one runner that knows about both.** Creates bidirectional dependency: selftest needs the test infrastructure, test infrastructure must not touch the real user home. Rejected.
- **Only ship pytest; tell users to run it if they hit trouble.** Works for developers, not for users. `lh selftest` is discoverable via `lh --help`; a test suite buried in `tests/` is not. Rejected.
- **Selftest as shell scripts (the predecessor approach).** Cannot return structured results, cannot be trivially extended, cannot run on Windows. Rejected.
- **Framework-wide health daemon that monitors continuously.** Overkill; the user runs selftest when they suspect something is wrong, not every minute.

## Consequences

- `lh selftest` is the first command users run after `lh init` or `lh migrate`. Its output is designed to be a punch list: every failing check includes a hint of what to try next.
- Adding a subsystem to the framework creates an obligation: ship a selftest check for it. The presence of `selftest/checks/<subsystem>_check.py` is how we know the subsystem is observable from outside.
- The runner's exception guard (`try: results = check() except BLE001`) means a crash inside one check does not abort the report. Users see partial results instead of silence.
- `CheckResult` uses a three-state status (`PASS | WARN | FAIL`). `WARN` is specifically for "the thing is configured but has a known-degraded mode" — e.g. knowledge directory exists but QMD is not installed. This is the axis the tri-state supports that a boolean cannot.
- Selftest checks are allowed to touch the user's real filesystem — that is the whole point. They must not write to the user's filesystem except in well-scoped locations (they never write outside `LH_*` directories). This is enforced by review, not by sandboxing.
- The parallel structure between `migrate/` (with `steps/`) and `selftest/` (with `checks/`) is deliberate: two subsystems that each iterate over a list of independent units with a shared result type. Future subsystems that fit the same shape will follow the same layout.
