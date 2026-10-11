---
description: Read-only audit of semantic drift between ADRs/backlog/docs and the code they describe
---

You are running a **read-only** audit of the semantic drift that no exact rule can decide: ADRs, `specs/backlog.md` and `docs/` pages describing behavior the code no longer has, or carrying stale status. This is Piece B of the coherence audit — the deterministic half already runs as pytest tests under `tests/docs/` on every `uv run --frozen pytest`; this command covers what those tests deliberately do not (prose claims, ADR status, backlog and roadmap freshness), not command/hook/config-field identity.

Do not edit any ADR, design, the backlog, the roadmap, or any file under `docs/`. This command reports and records. Fixing drift stays a human-reviewed action.

## 0. Read the ledger

Findings persist across runs in `coherence-drift.jsonl`, an append-only ledger owned by this command. It lives in the project memory directory beside `failures.jsonl`, but it is a separate file: this command never writes `failures.jsonl`.

**Locate the directory, do not guess it.** Run `lh memory status` and use the path on its `Store` line — that command resolves it exactly the way every hook does (`core/memory_store.py:memory_dir_for`, keyed by the repository's normalised git remote, so every worktree of one repository shares it). The same command lists `coherence-drift.jsonl` with its record count once the file exists. If it does not exist yet, every finding of this run is new; create the file on the first append.

Read every line and fold the ledger into its current state: group records by `key`; the record with the latest `ts` decides that key's status. The keys whose latest record is `"status": "open"` are the **open set**.

## 1. Re-verify every open entry

For each entry in the open set, re-check its claim against the current spec and code. The `line` it carries may have moved: find the claim by its text in `spec`, not by the number. Classify it:

- **still reproducing** — the doc still says it and the code still contradicts it. Keep it for the report, with its current line.
- **no longer reproducing** — the doc was fixed, the code changed to match, or the claim is gone. It gets a `resolved` record in step 6.

Do this before looking for new drift, so no open entry is left unexamined because the new findings ran long.

## 2. Read the specs and docs

Read every ADR under `specs/adrs/` whose header line reads `**Status:** accepted` (that exact bold-Markdown form, not a YAML key — see `specs/adrs/README.md` for the index and status vocabulary), and read `specs/backlog.md`. Then read every page under `docs/` that describes what the code does — in practice `docs/how/`, `docs/reference/`, `docs/architecture/` and `docs/agents/`. For each, note its central claims: what the doc says the code does, and what state it says a piece of work is in.

## 3. Spot-check the seed mapping

Start with these high-value ADR → module pairs (from `specs/designs/2026-06-20-coherence-audit-design.md`), then extend to any other ADR or `docs/` page you read in step 2 whose claims you can check against a real module:

| ADR | Module(s) to check |
|---|---|
| ADR-008 | `src/lazy_harness/knowledge/compound_loop*.py` |
| ADR-012 | `src/lazy_harness/monitoring/db.py` |
| ADR-023 / ADR-027 | `src/lazy_harness/knowledge/graphify.py`, `src/lazy_harness/deploy/engine.py` |
| ADR-033 | `src/lazy_harness/llm/` |

For each pair, read the module and compare it against the doc's claims. Does the code still do what the doc says it does? Is a described mechanism (e.g. an MCP server registration, a config field, a status) actually present?

## 4. Check the roadmap

`docs/roadmap.md` must reflect completed ADR items: an item whose ADR is accepted and whose implementation has shipped is ticked, and an unticked item is not already done. Each mismatch is a finding like any other, with `spec` pointing at the roadmap line.

## 5. Report findings

Report every finding of this run to the user — open entries still reproducing and new ones — in this exact format, one line per finding:

```
severity | spec:line | claim vs reality | suggested fix
```

- `severity`: `high` (code contradicts the doc's core claim), `medium` (partially stale), or `low` (cosmetic/status-only).
- `spec:line`: the file and current line number of the claim, e.g. `specs/adrs/023-graphify-code-structure.md:14`.
- `claim vs reality`: one line, e.g. "ADR claims Graphify runs as an MCP server; `deploy/engine.py` deliberately excludes it from `mcp_server_config()`."
- `suggested fix`: what a human should change — a doc edit, a status flip, a backlog line removal. Never apply it yourself.

Mark which findings are new in this run, and list the open entries that no longer reproduce, with the evidence for each. If you find nothing, say so explicitly — do not fabricate findings to have something to report.

## 6. Append to the ledger

Append one line per **change of state**, and nothing else:

- a **new** finding (its key is not in the ledger, or its latest record is `resolved`) → one `open` record;
- an open entry that **no longer reproduces** → one `resolved` record carrying the same `key`;
- an open entry that **still reproduces** → nothing. Its open record already says so; re-appending it is the noise this ledger exists to stop.

Each line is one JSON object:

```json
{"ts": "<ISO-8601 timestamp>", "key": "<spec path>#<anchor>", "status": "open",
 "severity": "<high|medium|low>", "spec": "<spec path>", "line": <line number at this run>,
 "claim": "<one-line claim vs reality>", "fix": "<the suggested fix from your report>"}
```

```json
{"ts": "<ISO-8601 timestamp>", "key": "<the open entry's key, verbatim>", "status": "resolved",
 "spec": "<spec path>", "evidence": "<why it no longer reproduces: the edit, the commit, the code now matching>"}
```

**The `key` must survive line shifts.** It is the spec path, `#`, and a short kebab-case anchor naming what the claim is about — the symbol, config field, command or status it concerns (`specs/adrs/031-default-hooks-merge.md#hook-entries-for-name`, `docs/how/hooks.md#graph-notice-staleness`). Never the line number: an edit above the claim would mint a new key and orphan the open one. Two distinct claims in one file need distinct anchors. When a finding of this run matches an open entry, reuse that entry's key verbatim instead of minting a new one.

**Append only** — never edit or remove an existing line. A resolved finding that drifts again later gets a new `open` record under its old key.

## What this does NOT do

- It does not auto-edit ADRs, designs, the backlog, the roadmap, or docs. It reports and records only.
- It does not write `failures.jsonl`, and so it no longer feeds the compound loop's `[EVITAR]` proposals or the failures tail `context-inject` shows at session start. Doc drift is a work queue for a human, not a recurring agent failure; it lives in `coherence-drift.jsonl` and nowhere else.
- It does not touch `tests/docs/` or anything the deterministic coherence tests already cover.

## Reference

See `specs/designs/2026-06-20-coherence-audit-design.md` for the full design (Piece A vs Piece B split) and the ledger contract.
