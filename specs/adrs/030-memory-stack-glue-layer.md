# ADR-030: Memory stack glue layer — discoverability, freshness, and consistency

**Status:** accepted
**Date:** 2026-05-05
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-016 (knowledge-dir-qmd-optional), ADR-022 (engram-episodic-memory),
ADR-023 (graphify-code-structure), ADR-024 (mcp-server-orchestration),
ADR-027 (memory-stack-overview), ADR-029 (engram-persist-deterministic-mirror)

## Context

ADR-027 named the five-layer memory model. ADR-029 closed the determinism gap on
Engram persistence. An audit on 2026-05-04 surfaced a different class of gap:
**the glue between layers is mostly prompted, not deterministic**. Across
sessions, projects, and accounts (`lazy` ↔ `flex`), behaviour drifts based on
whether the agent remembers its own conventions.

Concrete observations:

1. **Cold-start blindness on short sessions.** `compound_loop` gates
   (`min_messages=4`, `min_user_chars=200`, `debounce=60s`) skip evaluation, so
   no handoff / decisions / failures are produced. The next `SessionStart`
   loads `last_session_ctx` with only meta plus the first user message
   truncated to 80 chars, leaving no continuity.

2. **`MEMORY.md` curation drift.** Nothing pulls recurring patterns from
   `decisions.jsonl` into `MEMORY.md`. The 200-line ceiling exists only as a
   written rule; Claude Code truncates silently when the file exceeds it.

3. **QMD underused.** `qmd query` is fully agent-discretionary. No suggester
   runs against the current prompt or branch name to surface candidate vault
   notes at session start. Adherence to "use QMD" is prose, not code.

4. **Graphify barely surfaces.** `graphify-out/` has no freshness check
   against git HEAD; even when fresh, no part of the graph (central nodes,
   communities) is injected at session start. The agent reaches for the graph
   only when it remembers to. Result: the structural layer is installed but
   not absorbed into the workflow.

5. **`context_inject` truncation cascade is silent.** When the assembled body
   exceeds `max_body_chars` (default 3000), sections are dropped with no signal
   to the agent or user about what was lost.

6. **Engram ↔ JSONL coupling undocumented.** ADR-029 made Engram a deterministic
   mirror of JSONL, but ADR-027 still frames them as independent ("two layers
   because [...] coexist"). The user-facing model and the implementation
   diverged the moment ADR-029 shipped.

7. **Cross-profile drift.** `_common/CLAUDE.common.md` carries the canonical
   memoria copy across `lazy` and `flex`, but several entries are now
   incorrect or unenforced (e.g. "tope duro 200 líneas"; "Engram independiente
   de JSONL"). There is also no observability into which memory artifacts are
   shared across profiles vs. isolated, leaving silent inconsistencies
   possible across accounts.

## Decision

Add **deterministic glue components** between the existing layers, plus close
the doc/code consistency gap and the cross-profile observability gap. No new
layer is introduced; ADR-027's model stands. The following seven components
ship together as one integration milestone. Each is independently revertable.

### G1 — Cold-start `slim_handoff` fallback

When `compound_loop` gates block evaluation but the session emitted at least
one user prompt, run a **deterministic** fast-path that writes `handoff.md`
without an LLM call. Content: branch name, last user prompt verbatim, files
touched (from the `session_export` artifact), no decisions, no failures.

This preserves the contract that JSONL entries are LLM-curated while still
giving the next session enough context to resume.

New config: `compound_loop.slim_handoff_enabled = true` (default on).

### G2 — `MEMORY.md` size warning + opt-in consolidator

**Validator (deterministic, non-blocking).** New `PreToolUse` hook matching
`Edit|Write` on paths under `**/memory/MEMORY.md` that emits a warning via
`hookSpecificOutput.systemMessage` when the resulting file would exceed 200
lines. The write is **allowed**; the user receives a banner suggesting
consolidation. Implemented as `pre_tool_use_memory_size.py`. Fail-open if the
target path does not exist.

The bypass env var `LH_MEMORY_SIZE_BYPASS=1` silences the warning for the
G2 consolidator pathway.

**Consolidator (prompted, opt-in).** New CLI command `lh memory consolidate`
reads the last N JSONL entries (default 50), invokes one headless `claude -p`
call, and **proposes** a diff to `MEMORY.md`. The user reviews and applies
manually. The consolidator is intentionally not automated — `MEMORY.md` is the
curated semantic layer and human review is the contract (per ADR-027).

### G3 — QMD relevance suggester in `context_inject`

Extend `context_inject` to call `qmd query` (BM25 only, no rerank, `top_k=3`)
using a query string composed of the current branch name and the last user
prompt (if available from the session export). Emit results as a new section
`## Relevant vault notes` placed before `## Recent history`.

Latency budget: under 100 ms locally. Fail-soft if `qmd` is missing
(matches the ADR-016 pattern).

New config: `context_inject.qmd_suggest = { enabled = true, top_k = 3 }`
(default on).

### G4 — Graphify integration in `context_inject` (staleness + content)

`context_inject` gains a Graphify-aware section with two behaviours, depending
on the freshness of `graphify-out/graph.json` relative to
`git log -1 --format=%ct`:

**Stale graph (mtime older than HEAD).** Emit a single banner line:

```
## Notice
graphify-out/ is stale (last built YYYY-MM-DD, HEAD YYYY-MM-DD). Run /graphify to refresh.
```

No auto-rebuild — that decision was deferred by ADR-023 and remains deferred.
This component only surfaces the gap.

**Fresh graph (mtime ≥ HEAD).** Emit a `## Code structure` section containing,
in order:

- Top 3 nodes by degree centrality (file path + degree count)
- Top 3 communities by node count (label + node count)
- File count and language breakdown summary line

This is the missing piece that turns Graphify from "installed but unused" into
"absorbed into every session". Cost: one JSON read + trivial in-process
computation. Budget: under 50 ms.

If `graphify-out/graph.json` does not exist, both behaviours are silent
no-ops. Fail-soft on JSON parse errors with one log line.

New config: `context_inject.graphify_surface = { staleness_warn = true,
content_summary = true }` (both default on).

### G5 — Truncation visibility in `context_inject`

When `_truncate_body` drops a section to fit `max_body_chars`, prepend one
line to the output:

```
[truncated: dropped <section_names> to fit <max_chars>-char budget]
```

No behaviour change beyond making the existing silent loss observable. ~5-line
change in `context_inject.py`.

### G6 — Documentation consistency (governance, non-negotiable for this milestone)

Update three documents in the same change set to match the new implementation:

- `_common/CLAUDE.common.md` — Memoria section: state that the 200-line
  ceiling is enforced as a warning by G2; that Engram is a deterministic
  mirror of JSONL (cross-reference ADR-029); that QMD relevance and Graphify
  structure summaries are surfaced automatically by G3 and G4.
- `docs/architecture/overview.md` — add a paragraph on glue-layer determinism
  with a pointer to this ADR.
- `specs/adrs/027-memory-stack-overview.md` — annotate at the top: "see
  ADR-030 for the glue-layer integration that closes the prompted gaps in the
  model below." Per the index rules, the existing ADR is annotated, not
  rewritten.

Without G6, this ADR reproduces the drift it is fixing.

### G7 — Cross-profile consistency baseline

Add explicit, deterministic observability over what is shared across profiles
(`lazy`, `flex`) versus isolated. New CLI command `lh memory cross-profile-check`:

- Lists all memory artifacts per profile under `<config_dir>/projects/`.
- Flags inconsistencies: same project key (canonical via
  `git rev-parse --show-toplevel`) appearing in multiple profiles with
  divergent `MEMORY.md`, divergent `decisions.jsonl` tail, or divergent
  `handoff.md` mtime.
- Reports Engram cross-profile state: which projects have observations under
  multiple profile invocations (Engram itself stores in
  `~/.engram/engram.db`, single store, scoped by project key — divergence
  here usually indicates a project-key fragmentation issue, the same class
  ADR-029 fixed for fresh data).
- Reports `_common/CLAUDE.common.md` symlink integrity across profiles.

This is **observability only**. Cross-profile *sharing* of project memory
(e.g. surfacing a `lazy` project's decisions inside a `flex` session, or
vice versa) is intentionally out of scope for this ADR. Sharing requires its
own conflict-resolution model and a privacy review (work info crossing into
personal contexts and vice versa) and will be a separate ADR if and when the
need arises.

What is **already shared by design** (and now documented in G6) versus what
is **isolated**:

| Artifact | Cross-profile state |
|---|---|
| QMD vault index (`~/.cache/qmd/index.sqlite`) | Shared (single store, collection-scoped) |
| `_common/CLAUDE.common.md` | Shared via dotfile symlink |
| Engram store (`~/.engram/engram.db`) | Single store, partitioned by project / scope |
| `MEMORY.md`, `decisions.jsonl`, `failures.jsonl` | Isolated per profile |
| `handoff.md`, `pre-compact-summary.md` | Isolated per profile |
| `graphify-out/` | Per-repo (committable), independent of profile |

## Alternatives considered

- **Lower `compound_loop` gates instead of adding `slim_handoff` (G1).**
  Rejected. The gates exist because LLM evaluation is the most expensive part
  of the Stop chain. Lowering them turns every 2-message session into a
  billable evaluation. `slim_handoff` captures the continuity benefit at zero
  LLM cost.

- **Block writes when `MEMORY.md` exceeds 200 lines (instead of warning).**
  Considered for the validator. Rejected because legitimate consolidation
  edits can transiently exceed the budget mid-write; a hard block would force
  the user to plan around the validator. A non-blocking warning surfaces the
  problem without preventing work, and the consolidator pathway carries the
  bypass env var for its own writes.

- **Auto-curate `MEMORY.md` from JSONL on every Stop.** Rejected. ADR-027
  defines `MEMORY.md` as the curated semantic layer; auto-writes break the
  contract that the user owns this file. The opt-in consolidator preserves
  the contract.

- **Auto-rebuild Graphify on every commit (flip ADR-023's default).**
  Rejected for now. Re-graph cost on every commit is too high for active
  repos. The staleness banner in G4 gives the user enough signal to rebuild
  manually; a future ADR can flip the default if profiling shows the cost is
  acceptable.

- **Surface Graphify structure only when explicitly requested (skill-only).**
  Rejected. This is the status quo, and observation #4 documents that the
  graph is installed but rarely consulted. The cost of injecting a 5-line
  summary at SessionStart is negligible compared to the value of having the
  agent see "this repo's structure" without being prompted.

- **One unified `lh context-suggest` MCP server wrapping QMD / Engram /
  Graphify behind a single entry point.** Rejected as overengineering. Each
  MCP server already has a stable API; the agent already knows when to call
  each. The missing piece was *automatic surfacing at session start*, which
  `context_inject` is the right home for. A new MCP server would add a
  process, a deploy step, and a feature in `lh doctor` for no architectural
  gain.

- **Skip G6 and let docs drift.** Rejected. Doc/code drift is the
  meta-problem this ADR exists to fix. Shipping glue without updating the
  user-facing memoria copy reproduces the failure mode in observation #6.

- **Cross-profile sharing of project memory (in scope for this ADR).**
  Rejected as scope creep. Sharing introduces conflict resolution
  (whose `MEMORY.md` wins when both profiles edit), privacy classification
  (which project keys are work-only), and storage migration (per-profile
  directories vs. shared). G7 stops at observability, which is a one-day
  feature that gives the data to decide whether sharing is even desirable.

- **Per-component ADRs (one each for G1–G7).** Considered. Rejected because
  the components share a single theme — they connect existing primitives
  rather than adding new ones — and a single coherent narrative makes the
  trade-offs visible. Each component still gets its own design + plan under
  `specs/designs/` and `specs/plans/`, so independent review is preserved.

## Consequences

**Positive**

- Every session produces at least slim continuity (G1), eliminating
  cold-start blindness on short sessions.
- `MEMORY.md` 200-line ceiling becomes a visible warning instead of a silent
  CC truncation (G2).
- Vault relevance is surfaced automatically (G3), reducing dependence on the
  agent's discretionary recall of "use QMD".
- Graphify becomes part of every SessionStart for repos with a fresh graph
  (G4 fresh-path), and a stale graph stops answering queries silently
  (G4 stale-path).
- Truncation losses are visible (G5), making the 3000-char budget tunable
  based on real evidence.
- The user-facing memoria copy matches the implementation (G6), closing the
  most recent drift.
- Cross-profile inconsistencies are detectable on demand (G7), giving the
  user one command to verify that `lazy` and `flex` agree where they should
  and disagree where they should.
- All glue components are profile-independent and load identically for
  `lazy` and `flex`, giving consistent behaviour across accounts.

**Negative**

- `context_inject` runs more work at SessionStart (qmd query + graphify
  freshness check + graph JSON read). Budget: under 200 ms additional latency
  total; fail-soft if any tool or artifact is missing.
- `compound_loop.py` gains a branch (gate-blocked → slim path), increasing
  test surface.
- Six new config knobs in three sub-tables increase wizard surface for
  ADR-026. Mitigated by sensible defaults (all glue components default-on).
- The G2 warning may be ignored if it appears on every save; if that proves
  noisy in practice, a follow-up ADR can rate-limit it.
- The G4 fresh-path adds a JSON read on every SessionStart in repos with
  large `graphify-out/graph.json`. Threshold for concern is files above
  ~5 MB; below that the parse stays under budget.

**Coupling note (resolves observation #6)**

ADR-027's "two episodic layers coexist" framing is updated by G6 to: "two
episodic layers serve different query profiles over the same data". The table
itself does not change — the layers still expose distinct interfaces. Only
the prose justification is corrected.

## Implementation

Each component gets its own design + plan under `specs/designs/` and
`specs/plans/`, following the ADR-029 pattern. Recommended sequence (each
step independently shippable and revertable):

1. **G5** (truncation visibility) — minimal change, ships first because it
   makes the effects of G3/G4 observable.
2. **G2 validator** — independent, low-risk PreToolUse hook (warning path).
3. **G1 slim handoff** — depends on the session-export artifact schema.
4. **G3 QMD suggester** — depends on `qmd` binary detection
   (already provided by ADR-025 features helper).
5. **G4 staleness banner** — independent.
6. **G4 fresh-graph content summary** — depends on a small graph-reader
   helper in `lazy_harness/knowledge/graphify.py`.
7. **G7 cross-profile check** — independent CLI command.
8. **G2 consolidator** (`lh memory consolidate`) — last, builds on G2
   validator.
9. **G6 doc updates** — bundled with G3 and G4 (the most user-visible
   components).

This sequence keeps every step independently shippable and revertable. The
milestone closes when all seven components are live in both `lazy` and
`flex` profiles after the next `lh deploy`.
