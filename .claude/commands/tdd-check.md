---
description: Run the full pre-commit verification suite — pytest, ruff, mkdocs build
---

You are running the complete verification suite that must pass before any commit in this repo. Run the three checks in sequence, reporting each one's result clearly. If any check fails, stop and report the failure — do not try to fix it automatically.

## 1. Tests — `uv run pytest`

```bash
uv run pytest
```

Pass criteria: exit code 0, zero warnings, zero deprecation notices, zero skipped tests without an explicit `@pytest.mark.skip` reason. If the output is noisy even on pass, treat that as a failure and report it.

## 2. Lint — `uv run ruff check src tests`

```bash
uv run ruff check src tests
```

Pass criteria: exit code 0, no findings.

## 3. Docs build — `uv run --group docs mkdocs build --strict`

```bash
uv run --group docs mkdocs build --strict
```

Pass criteria: exit code 0, no broken links, no unrecognised config, no nav warnings. `--strict` escalates warnings to errors, so this is the authoritative check.

## Report

After all three complete, summarise:

- ✅ / ❌ per check
- If everything passed: confirm the tree is ready to commit.
- If anything failed: show the relevant failing lines and stop. Do not attempt fixes in this command — the user drives the fix.

## Why this exists

This is the pre-commit checklist from `CLAUDE.md` made executable. Running it as a single command removes the temptation to skip one of the three under time pressure. TDD discipline depends on the full suite being green before you commit — not just the test you just added.

See `superpowers:test-driven-development` for the broader TDD workflow.
