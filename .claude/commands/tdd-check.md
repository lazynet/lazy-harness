---
description: Run the full pre-commit verification suite — pytest, ruff lint, ruff format, mkdocs build
---

You are running the complete verification suite that must pass before any commit in this repo. Run the four checks in sequence, reporting each one's result clearly. If any check fails, stop and report the failure — do not try to fix it automatically.

## 1. Tests — `uv run --frozen pytest`

```bash
uv run --frozen pytest
```

Pass criteria: exit code 0, zero warnings, zero deprecation notices, zero skipped tests without an explicit `@pytest.mark.skip` reason. If the output is noisy even on pass, treat that as a failure and report it.

## 2. Lint — `uv run --frozen ruff check src tests`

```bash
uv run --frozen ruff check src tests
```

Pass criteria: exit code 0, no findings.

## 3. Format — `uv run --frozen ruff format --check src tests`

```bash
uv run --frozen ruff format --check src tests
```

Pass criteria: exit code 0, zero files reported as needing reformatting.

Distinct from check 2, not a duplicate of it: `ruff check` runs lint rules and
leaves layout alone, so a repo gated only on it drifts silently until somebody
runs the formatter and lands 44 reformatted files on top of whatever they were
actually changing. Fix by running `uv run --frozen ruff format src tests` and
committing the result on its own.

## 4. Docs build — `uv run --frozen --group docs mkdocs build --strict`

```bash
uv run --frozen --group docs mkdocs build --strict
```

Pass criteria: exit code 0, no broken links, no unrecognised config, no nav warnings. `--strict` escalates warnings to errors, so this is the authoritative check.

## Report

After all four complete, summarise:

- ✅ / ❌ per check
- If everything passed: confirm the tree is ready to commit.
- If anything failed: show the relevant failing lines and stop. Do not attempt fixes in this command — the user drives the fix.

## Why this exists

This is the pre-commit checklist from `CLAUDE.md` made executable. Running it as a single command removes the temptation to skip one of the four under time pressure. TDD discipline depends on the full suite being green before you commit — not just the test you just added.

See `superpowers:test-driven-development` for the broader TDD workflow.
