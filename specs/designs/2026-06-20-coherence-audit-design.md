# Coherence audit — deterministic doc tests + semantic ADR/backlog skill

**Date:** 2026-06-20
**Status:** Accepted — ready to implement
**Related:** Non-negotiable #6 in `CLAUDE.md` ("Docs coherence is audited before every release"); audit findings 2026-06-20 (public-doc drift in `docs/reference/*`, ADR drift in `specs/adrs/023`, `027`, `012`, `008`, stale `specs/backlog.md`).

## Problem

The repo declares invariants that only a human verifies, so they drift. The 2026-06-20 audit found two distinct classes of drift:

1. **Deterministic drift** — the public docs name commands, hooks, and config fields that no longer match the code. Examples: `docs/getting-started/first-run.md` references `lh profile deploy` and `lh profile ls` (neither exists); `docs/reference/config.md` documents a `session-context` hook that is not registered. These are decidable by exact comparison: does the documented name exist in the code's surface?

2. **Semantic drift** — ADRs and the backlog describe behavior the code no longer has, or status that is stale. Examples: ADR-023 and ADR-027 present Graphify as an MCP server, but `deploy/engine.py` deliberately excludes it and `mcp_server_config()` was never written; `specs/backlog.md` still lists Ollama backend work that ADR-033 already shipped. These require reading and judgment, not a list diff.

Non-negotiable #6 already mandates this audit "before every release", but as a manual step. Manual invariants drift. This design makes the deterministic half an executable invariant and the semantic half a repeatable agent-driven skill.

## Design

Two pieces, each in its proper terrain.

### Piece A — Deterministic coherence (pytest tests)

Three tests under `tests/docs/` that fail the existing `uv run pytest` gate when public docs diverge from the code surface. No new CLI surface, no `lh selftest` change (selftest checks *install health*, not repo-doc coherence — a category mismatch). Drift becomes a red build.

| Test file | Asserts | Source of truth |
|---|---|---|
| `tests/docs/test_cli_reference_coherence.py` | every `lh <command> [subcommand]` named anywhere under `docs/**`, not just in `docs/reference/cli.md`, exists | the click command tree (`lazy_harness.cli.main.cli`) |
| `tests/docs/test_hooks_doc_coherence.py` | every built-in hook documented in `docs/how/hooks.md` is registered, and every registered built-in is documented | `_BUILTIN_HOOKS` in `hooks/loader.py` |
| `tests/docs/test_config_reference_coherence.py` | every config field documented in `docs/reference/config.md` exists on the corresponding dataclass | the config dataclasses in `core/config.py` |

**Direction: `doc ⊆ code` (lax).** A documented command/hook/field that does not exist in code is a failure (catches copy-paste rot and renames). The reverse direction (every code symbol must be documented) is intentionally *not* enforced, to avoid false positives on intentionally-undocumented internals. The hooks test is the one exception where the reverse is cheap and valuable (a small fixed registry), so it asserts both directions.

**Parsing approach:** each test extracts candidate names from the doc with a narrow, anchored regex (e.g. fenced ```` ```bash ```` blocks and inline-code `lh ...` spans for the CLI test; the `### <hook-name>` headings for hooks; the `` `field_name` `` cells of the config tables). The extractor is deliberately conservative: it recognizes a bounded shape, and anything it cannot classify is ignored rather than guessed. Comments in the test name the doc anchors it relies on, so a doc restructure that breaks the anchor fails loudly rather than silently passing.

**Self-testing:** each test ships with a sibling unit that feeds the extractor a small inline doc fragment containing one known-good name and one known-bad name, and asserts the checker flags exactly the bad one. This proves the test can fail before we trust it passing — the same discipline as TDD applied to the linter itself.

### Piece B — Semantic coherence (`/coherence-audit` skill)

A slash command `.claude/commands/coherence-audit.md` that dispatches a read-only agent to cross-check `specs/adrs/` and `specs/backlog.md` against the code, then reports drift that no exact rule can decide.

**Flow:**
1. The agent reads each active ADR's status and central claims, and the backlog's open/done items.
2. For each, it spot-checks the modules the doc describes (the skill body lists the high-value ADR→module mappings as starting points: ADR-008→`knowledge/compound_loop*.py`, ADR-012→`monitoring/db.py`, ADR-023/027→`knowledge/graphify.py` + `deploy/engine.py`, ADR-033→`llm/`).
3. It reports findings to the user as `severity | spec:line | claim vs reality | suggested fix`.
4. It records each change of state in its own append-only ledger, `coherence-drift.jsonl`, in the project memory dir. *(Originally: one `failures.jsonl` record per unresolved drift on every run — superseded on 2026-10-11, see Evolution.)*

**Append contract:** the ledger contract under Evolution 2026-10-11 replaces the original one, which promised that a re-run would not double-record a finding while delegating deduplication to the compound loop. The loop never deduplicated these rows (see Evolution), and the two halves of that sentence contradicted each other.

### What this does NOT do (YAGNI)

- It does not auto-edit ADRs, designs, the backlog, or docs. It only reports and records. Fixing drift stays a human-reviewed action.
- It does not generate CLAUDE.md rule proposals (the rejected "full" option). Since 2026-10-11 it does not feed them indirectly either: findings no longer reach `failures.jsonl`.
- Piece A does not validate prose, descriptions, or examples — only the identity of commands, hooks, and config fields.
- Piece A does not touch `lh selftest`. Runtime health and repo-doc coherence stay separate concerns.

## Testing strategy

- **Piece A** is tests; the tests are the deliverable. Each is accompanied by a self-test (above) proving the extractor flags a planted bad name. Under TDD, the self-test is written and seen failing before the extractor exists.
- **Piece B** is a markdown skill, not code. It is validated by running it against the real repo and confirming it surfaces the drifts the 2026-06-20 audit already documented (ADR-023/027 Graphify-as-MCP, ADR-012 single-table, stale backlog Ollama item). A run that misses those known drifts is a failed skill.

## Consequences

- The deterministic half of non-negotiable #6 becomes an executable invariant that fails the gate, removing a manual release step.
- The semantic half becomes a one-command repeatable audit whose findings persist into the memory stack rather than evaporating at end of session.
- New surface added: three test files under `tests/docs/` (plus their self-tests) and one slash command. No new runtime code paths, no new CLI commands, no new dependencies.
- Risk: an over-eager extractor in Piece A produces false-positive build failures. Mitigated by the lax `doc ⊆ code` direction, conservative anchored parsing, and the self-tests that pin extractor behavior.

## Evolution

**2026-10-11: findings move from `failures.jsonl` to a ledger of their own.** The original append contract recorded every unresolved finding into `failures.jsonl` on every run and relied on "the compound loop already dedupes". It does not, for these rows: the loop's only deduplication is an instruction in its distillation prompt (`knowledge/compound_loop.py`, the "Recent failures already recorded" block) covering the failures the worker itself writes from a session transcript; nothing reads `failures.jsonl` back to collapse rows another writer appended. Measured on the live store before this change: 349 rows tagged `coherence-audit` over 296 distinct `spec:line` keys, 345 of them `unresolved`, with no record shape that could later mark a finding fixed — so each release re-appended the findings still open and the file never said which ones had closed. The cost was not only disk: `context-inject` shows the `failures.jsonl` tail at every session start, and 26 of its last 40 lines were doc-drift rows, displacing the agent failures that section exists to surface.

The contract now:

- **Target.** `coherence-drift.jsonl` in the project memory directory (the `Store` path `lh memory status` prints, which also lists the file's record count). The command never writes `failures.jsonl`; the rows already there stay as they are, append-only.
- **Record.** `{"ts", "key", "status", "severity", "spec", "line", "claim", "fix"}` for an `open` record; `{"ts", "key", "status", "spec", "evidence"}` for a `resolved` one.
- **Key.** `<spec path>#<anchor>`, the anchor a short kebab-case name for the symbol, field, command or status the claim concerns. The line number is carried as data, never as identity, so an edit above the claim neither orphans an open entry nor mints a duplicate.
- **State.** A key's status is the status of its latest record. Append-only: a resolved key that drifts again gets a new `open` record under the same key.
- **Re-run.** The command reads the ledger first and re-verifies every open entry before looking for new drift. It appends (a) nothing for an open entry still reproducing, (b) one `open` record for a finding whose key is absent or resolved, (c) one `resolved` record, with evidence, for an open entry that no longer reproduces. A run that changes no state appends nothing.

Two scope changes landed with it. The command now reads the `docs/` pages that describe a mechanism (`docs/how/`, `docs/reference/`, `docs/architecture/`, `docs/agents/`), since the 0.89.2 run reported four drifts there that step 1 never asked it to look for. And the roadmap check — `docs/roadmap.md` reflects completed ADR items — moved from the release non-negotiable in `AGENTS.md` into the command as its own step, so the audit has one definition.

The consequence the original design counted as a feature is gone on purpose: coherence findings no longer flow into the compound loop's `[EVITAR]` proposals. Doc drift is a queue of edits for a human, not a recurring agent mistake, and the proposals it produced restated audit findings rather than preventing anything.
