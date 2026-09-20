# External hook ownership — definitive gate

Date: 2026-09-19

Result: **DONE**

| Check | Exit code | Counts | Result |
| --- | ---: | --- | --- |
| `uv run --frozen pytest -q` | 0 | 5,223 passed; 0 failed; 0 skipped; 0 warnings | PASS |
| `uv run --frozen ruff check src tests` | 0 | 0 findings | PASS |
| `uv run --frozen ruff format --check src tests` | 0 | 502 files already formatted; 0 requiring reformatting | PASS |
| `uv run --frozen --group docs mkdocs build --strict` | 0 | 0 strict build errors; 0 MkDocs strict warnings | PASS |
| `git diff --check` | 0 | 0 whitespace errors | PASS |

The first sandboxed pytest invocation exited 2 before collection because `uv`
could not open its cache. The exact command was rerun with escalated cache
access and produced the passing result above.

The documentation log included one informational banner from the Material for
MkDocs team concerning MkDocs 2.0. It did not register as a MkDocs warning or
error under `--strict`; the build completed successfully in 1.20 seconds.

Full command output was redirected to:

- `/private/tmp/external-hook-ownership-definitive-pytest.log`
- `/private/tmp/external-hook-ownership-definitive-ruff-check.log`
- `/private/tmp/external-hook-ownership-definitive-ruff-format.log`
- `/private/tmp/external-hook-ownership-definitive-mkdocs.log`
- `/private/tmp/external-hook-ownership-definitive-git-diff-check.log`

DONE
