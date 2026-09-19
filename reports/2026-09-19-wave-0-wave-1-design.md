# Wave 0 closeout and Wave 1 design

Date: 2026-09-19\
Branch: `docs/wave-0-wave-1-design`\
Worktree: `/Users/lazynet/repos/lazy/lazy-harness/.worktrees/wave-0-wave-1-design`

## Outcome

Wave 0 is closed. The multi-agent implementation remains accepted; the true
residuals are the 2026-11-11 adoption kill criterion, the deferred opencode
lane, user-hook command ownership, portable skill projection, portable repo
instructions, honest Codex cost comparison and project-state persistence.

Wave 1 now has three proposed decisions:

- ADR-060 makes `AGENTS.md` canonical and `CLAUDE.md` an importing native
  appendix, piloted in lazy-harness, lazy-ai-tools and dotfiles.
- ADR-061 separates actual billed cost from API-equivalent list price and
  prices responses before aggregation.
- ADR-062 adds an opt-in generated `Última sesión` PRJ section instead of
  letting inference rewrite human-curated project state.

ADR-059's trigger is met and its implementation joins Wave 1. The concrete
trigger is `lazymind-projects`: the shared system contract requires it for PRJ
work, but the skill is present only in the Claude Code profile and absent from
the Codex catalog.

## Wave 0 evidence

The local 48-hour `lazy-codex` window contains 53 sessions, 329,086,779 input
tokens, 161,709,312 cached-input tokens and 562,691 output tokens. The current
flat-rate path correctly does not call those tokens billed spend, but Grafana's
generic `cost` aggregation leaves no API-equivalent comparison.

Sanitized fixtures capture one real `turn_context` and `token_count` pair for
`gpt-5.6-sol`, `gpt-6-astra` and `codex-auto-review`. Public standard-tier
rates were captured for the first two. `codex-auto-review` and the official
short/long threshold remain explicitly unknown; Wave 1 must not invent them.

The stale F7 backlog item is closed by existing integration coverage:
`test_session_start_preflight_reads_the_invoked_profiles_credentials` and
`test_sync_claude_regenerates_the_doc_of_the_agent_the_invoked_profile_runs`.

## Why the PRJ did not update

Nothing was lost. The general update never existed.

`session_end.main()` records `session_closed` and force-enqueues compound-loop.
`process_task()` resolves a PRJ only after successful inference, and then only
calls `append_grade_to_prj_backlog()` for poor or acceptable-with-issues grades.
That helper inserts one regression under an exact heading. It does not update
`Estado actual`, record successful sessions or bump frontmatter `updated`.

`PRJ-LazyHarness` is still dated 2026-09-14 and has 12,570 words. `vaultkit
status` requires archival above 5,000. A targeted sync could not add a new
section (`section not present — run rewrite first`), and silently rewriting or
archiving that history was outside this wave.

A TaskNote was created at
`LazyMind/TaskNotes/Tasks/TASK-ejecutar-wave-1-skills-portables-pilotos.md`,
linked to `PRJ-LazyHarness` by frontmatter. It does not mutate the PRJ.

Tooling defect found: `vaultkit task` created that file on the invocation
without `--apply`; the following `--apply` invocation returned `ya existe`.
That contradicts the skill's dry-run-first contract and belongs in
lazy-ai-tools, not in this repository.

## Wave 1 execution order

1. Implement ADR-059 capability, collision planning and ledger cleanup.
2. Archive `PRJ-LazyHarness` through a reviewed `vaultkit rewrite`, then add
   the opt-in generated section required by ADR-062.
3. Implement ADR-062 worker persistence and installed-agent probes.
4. Run the three ADR-060 repo pilots and hold the seven-working-day gate.
5. Resolve the official context-tier boundary and implement ADR-061 locally.
6. Deploy the v4-tolerant receiver, emit v4, backfill, then update Grafana.
7. Migrate the remaining repositories only after the pilot gate closes.

## Files

- `specs/adrs/059-portable-skills-native-commands-agents.md`
- `specs/adrs/060-agents-md-is-the-portable-repository-contract.md`
- `specs/adrs/061-billed-cost-and-api-equivalent-cost-are-separate.md`
- `specs/adrs/062-session-end-publishes-bounded-project-state.md`
- `specs/designs/2026-09-19-portable-repository-instructions-design.md`
- `specs/designs/2026-09-19-billed-and-api-equivalent-cost-design.md`
- `specs/designs/2026-09-19-session-project-state-sync-design.md`
- `specs/designs/2026-09-19-codex-pricing-evidence.md`
- `specs/gates/fixtures/codex-pricing/`
- `specs/backlog.md`, `docs/roadmap.md`, `specs/adrs/README.md`

## Verification

- `uv run --frozen pytest -q` — 4,991 passed.
- `uv run --frozen ruff check src tests` — passed.
- `uv run --frozen ruff format --check src tests` — 492 files formatted.
- `uv run --frozen --group docs mkdocs build --strict` — passed; emitted only
  Material for MkDocs' upstream MkDocs 2.0 advisory.
- `git diff --check` — passed.
