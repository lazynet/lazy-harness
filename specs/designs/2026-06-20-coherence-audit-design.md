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
4. For each **unresolved** drift, it appends one record to `failures.jsonl` in the project memory dir, with a root-cause line. This is the auto-learning hook: the existing compound-loop and claude-md proposals lifecycle (PR #99) already consume `failures.jsonl`, so no new persistence infrastructure is built — coherence findings flow into the memory stack that already exists.

**Append contract:** the skill appends, never edits existing lines (matching the append-only rule for `failures.jsonl`). Each record carries enough to dedupe on re-run (the `spec:line` + claim), so running the skill twice does not double-record the same unresolved drift. Deduplication is the consumer's job (the compound loop already dedupes); the skill's contract is only "append a well-formed record once per run per finding".

### What this does NOT do (YAGNI)

- It does not auto-edit ADRs, designs, the backlog, or docs. It only reports and records. Fixing drift stays a human-reviewed action.
- It does not generate CLAUDE.md rule proposals directly (the rejected "full" option). That path already exists via the proposals lifecycle consuming `failures.jsonl`; wiring a second producer is premature.
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
