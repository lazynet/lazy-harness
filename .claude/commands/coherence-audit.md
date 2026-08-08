---
description: Read-only audit of semantic drift between ADRs/backlog and the code they describe
---

You are running a **read-only** audit of the semantic drift that no exact rule can decide: ADRs and `specs/backlog.md` describing behavior the code no longer has, or carrying stale status. This is Piece B of the coherence audit — the deterministic half already runs as pytest tests under `tests/docs/` on every `uv run pytest`; this command covers what those tests deliberately do not (prose claims, ADR status, backlog freshness), not command/hook/config-field identity.

Do not edit any ADR, design, the backlog, or any file under `docs/`. This command reports and records. Fixing drift stays a human-reviewed action.

## 1. Read the specs

Read every ADR under `specs/adrs/` whose header line reads `**Status:** accepted` (that exact bold-Markdown form, not a YAML key — see `specs/adrs/README.md` for the index and status vocabulary), and read `specs/backlog.md`. For each, note its central claims: what the doc says the code does, and what state it says a piece of work is in.

## 2. Spot-check the seed mapping

Start with these high-value ADR → module pairs (from `specs/designs/2026-06-20-coherence-audit-design.md`), then extend to any other ADR you read in step 1 whose claims you can check against a real module:

| ADR | Module(s) to check |
|---|---|
| ADR-008 | `src/lazy_harness/knowledge/compound_loop*.py` |
| ADR-012 | `src/lazy_harness/monitoring/db.py` |
| ADR-023 / ADR-027 | `src/lazy_harness/knowledge/graphify.py`, `src/lazy_harness/deploy/engine.py` |
| ADR-033 | `src/lazy_harness/llm/` |

For each pair, read the module and compare it against the ADR's claims. Does the code still do what the ADR says it does? Is a described mechanism (e.g. an MCP server registration, a config field, a status) actually present?

## 3. Report findings

For every drift you find, report it to the user in this exact format, one line per finding:

```
severity | spec:line | claim vs reality | suggested fix
```

- `severity`: `high` (code contradicts the doc's core claim), `medium` (partially stale), or `low` (cosmetic/status-only).
- `spec:line`: the file and line number of the claim, e.g. `specs/adrs/023-graphify-code-structure.md:14`.
- `claim vs reality`: one line, e.g. "ADR claims Graphify runs as an MCP server; `deploy/engine.py` deliberately excludes it from `mcp_server_config()`."
- `suggested fix`: what a human should change — a doc edit, a status flip, a backlog line removal. Never apply it yourself.

If you find nothing, say so explicitly — do not fabricate findings to have something to report.

## 4. Persist unresolved drift

For every finding that is **not** resolved during this run (i.e. every finding you reported — this command never edits docs, so nothing gets resolved in-command), append one record to `failures.jsonl` in the project memory directory.

**Locate the file first, do not guess the path.** The project memory directory follows the ADR-032 pattern used throughout this codebase (`_project_memory_dir` in `src/lazy_harness/cli/doctor_cmd.py` and `src/lazy_harness/cli/memory_cmd.py`): `<agent runtime dir>/<sessions subdir>/<encoded cwd>/memory/`, where the cwd is encoded by replacing `/` with `-` (e.g. `/Users/x/repo` → `-Users-x-repo`). For a default Claude Code setup this resolves to `~/.claude/projects/<encoded-cwd>/memory/failures.jsonl`. Read `docs/how/memory-compound.md` for the full mechanics and an example of the exact JSON shape before writing anything — do not invent fields.

Each appended line is one JSON object with this schema (matching what `persist_results` in `src/lazy_harness/knowledge/compound_loop.py` writes, so the compound loop and `context-inject` hook can consume it like any other failure record):

```json
{"ts": "<ISO-8601 timestamp>", "type": "failure",
 "summary": "<severity> | <spec:line> | <one-line claim vs reality>",
 "root_cause": "<why the doc and code diverged>",
 "resolution": "unresolved — pending human-reviewed doc edit",
 "prevention": "<the suggested fix from your report>",
 "project": "<basename of the repo working directory>",
 "tags": ["coherence-audit"]}
```

**Append only** — never edit or remove an existing line in `failures.jsonl`. Put the `spec:line` and the claim text in `summary` so a re-run's findings can be deduped against prior entries; deduplication itself is the consumer's job (the compound loop already dedupes when it distills failures), not this command's.

## What this does NOT do

- It does not auto-edit ADRs, designs, the backlog, or docs. It reports and records only.
- It does not generate `CLAUDE.md` rule proposals directly — that already happens downstream, when the compound loop distills recurring `failures.jsonl` entries into `[EVITAR]`-prefixed proposals. This command only feeds that existing pipeline.
- It does not touch `tests/docs/` or anything the deterministic coherence tests already cover.

## Reference

See `specs/designs/2026-06-20-coherence-audit-design.md` for the full design (Piece A vs Piece B split) and `docs/how/memory-compound.md` for the `failures.jsonl` write path and schema this command depends on.
