# ADR-015: Strict test-driven development as a non-negotiable workflow

**Status:** accepted
**Date:** 2026-04-13

## Context

Most of the framework's subsystems are the kind of code that fails silently: hooks that are supposed to run but don't, migrations that look like they succeeded but corrupted one file, path resolvers that work on the author's machine and break on a user's XDG-configured Linux. The only way to catch this class of bug is with tests that were written **before** the code they cover, because a test written afterward is shaped by the implementation it was supposed to check.

The framework also has more contributors than just the author, including AI coding agents. "Agents write the test after they write the code" is the default failure mode we observed during development of the predecessor. The discipline has to be encoded in the project rules so that agents cannot rationalize it away.

## Decision

**Strict red-green-refactor TDD is the only way production code is added to this repository.** Documented in `CLAUDE.md` at repo root. The iron law: **no production code exists without a failing test that exercised it first.** This applies to new features, bug fixes, and refactors alike.

The cycle, applied every time:

1. **RED.** Write one failing test for one behavior. Real code over mocks unless a dependency genuinely cannot be exercised (e.g. `claude -p` is injected as a callable so tests can substitute it).
2. **Verify RED.** Run the test and watch it fail. Confirm the failure is "feature missing", not a typo. A test that passes immediately proves nothing.
3. **GREEN.** Write the minimal code to make the test pass. No extras, no speculation.
4. **Verify GREEN.** Re-run the test plus the full suite. Output must be pristine — no warnings, no deprecation noise.
5. **REFACTOR.** Clean up while staying green. Do not add behavior in this step.
6. **Repeat.**

Bug fixes follow the same cycle: reproduce the bug as a failing test first, then fix. This guarantees the fix is real and the regression is guarded.

## Alternatives considered

- **Test after implementation.** Standard practice in most codebases. Rejected for this repo because tests-after-the-fact end up shaped to the implementation; they miss the edge cases the implementation missed.
- **"Test where it matters" (selective TDD).** The categories of "where it matters" always shrink under deadline pressure, and the uncovered code always turns out to be where the bug was. Rejected.
- **Coverage threshold as the discipline.** Coverage measures lines executed, not behaviors verified. A test that imports a module and asserts nothing still counts. Rejected as a standalone discipline — the repo enforces TDD by process, not by coverage gate.
- **TDD for the framework but not for docs / ADRs.** Kept. TDD applies to executable code, not to prose. ADRs and docs pages go through review but not through a red-green cycle.

## Consequences

- Every module under `src/lazy_harness/` has a one-to-one counterpart under `tests/`. This is enforced by review, and the structural mirror is visible in the layout cheatsheet.
- Test suite runs in a few seconds and is expected to pass cleanly on every commit. `uv run pytest` is part of the pre-commit checklist for every change.
- Refactors are safe by construction. The red-green-refactor cycle means any refactor starts from a green suite and ends at a green suite, with the intermediate step being pure structural change.
- AI agents (including Claude Code itself when editing this repo) are told about the rule in `CLAUDE.md` and must comply. An agent that writes code first is instructed to delete it and start over.
- The TDD rule is the reason several subsystems are structured as flat pure functions (`knowledge/compound_loop.py`, `knowledge/session_export.py`): pure functions are trivial to test without mocking. Shape follows testability.
- Docs and ADRs are explicitly out of scope for the rule — they go through human review but not through a test cycle. This ADR itself was written without a test.
- Speed of development is not sacrificed. For code this size the red-green cost is dominated by typing speed, and the rewrite cost of a bug that escapes to production is an order of magnitude higher. The discipline pays its cost back in the first real regression it prevents.
