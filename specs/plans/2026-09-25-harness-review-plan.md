# Harness review implementation plan

Date: 2026-09-25. Starting revision: `94be6b3f`.

## Objective and execution contract

Close the verified isolation, security, memory-delivery and recovery defects;
make effective configuration observable; reconcile instructions with shipped
capabilities; measure context and verification costs before changing policy.

The coordinating session plans, reviews and verifies. Implementation runs in
visible Herdr worktree panes, at most three concurrently. Each unit follows
strict TDD and the four pre-commit gates in `.claude/commands/tdd-check.md`.
Workers commit locally and never push, merge, deploy, change credentials or
edit shared backlog/ADR indexes. The coordinator owns shared documentation.
No production hook is deployed from a worktree. Publication and installation
precede runtime changes, as required by the repository contract.

This plan is based on local inspection and isolated reproductions, not a
claim of production data leakage. Existing fleet migration windows and the
Graph Assist experiment ending 2026-10-09 remain in force.

## Units and file ownership

| ID | Branch | Owned scope | Lane | Dependencies |
| --- | --- | --- | --- | --- |
| A | `fix/review-isolation` | hook profile fallback; session lookup; QMD suggestion scope; associated config/tests | Codex high | none |
| B | `fix/review-security` | security classifier, typed exception handling and its tests | Codex high | none |
| C | `fix/review-backup` | migration backup, rollback and recovery tests | Sonnet | none |
| D | `fix/review-memory` | curated memory injection and context tests | Sol Medium | A |
| F | `fix/review-diagnostics` | monitoring read-only access; doctor/selftest partial failures | Sonnet | C |
| E | `feat/review-effective-config` | effective configuration and capability diagnostics | Sol Medium | A, B, D, F |
| H | `feat/review-context-budget` | aggregate contract/context inventory and measurements | Sol Medium | D, E |
| I | `feat/review-proposal-drain` | held-proposal review/requeue and associated CLI tests | Sol Medium | H |
| J | `feat/review-fleet-contracts` | repository contract inventory and explicit exceptions | Sol Medium | E |
| G | `docs/review-profile-contracts` | reviewed profile/skill/permission patches and rollout checks | Sol Medium (design) | B, D, E, H, J |
| K | `chore/review-verification-cost` | gate measurements and evidence-backed proposal | Sol Medium (analysis) | implementation units |
| L | `docs/review-adoption-checks` | adoption/retirement criteria and evidence matrix | Sol Medium (design) | H, I, K |

Model policy updated after A/B completed: only the orchestrator uses Astra High.
All remaining Codex lanes use Sol Medium; Claude lanes use Sonnet. A/B's model
entries record their completed execution, not a future dispatch default.

Dependencies describe final integration requirements. Independent sections can
proceed concurrently with explicit ownership; shared-file changes are integrated
serially. Before dispatch, inspect current HEAD and other lanes. New ADR numbers
are allocated only by the coordinator. Review focused evidence and candidate
diffs before starting the full gate, so review corrections do not waste a suite.

## Acceptance criteria

### A — Isolation

- An unknown profile never silently selects another identity. Preserve a
  correct refusal wire format when the calling agent can be identified.
- Last-session lookup uses canonical project identity and exact matches;
  test equal basenames across owners and prefix collisions (`api`/`api-admin`).
- QMD suggestions have an explicit scope resolved for the invoked profile.
  Missing scope abstains from automatic global search; interactive searches
  keep their separately authorized behavior.
- Test configuration round trips and existing/new-document paths for any new
  configuration. No production collection configuration is guessed.

### B — Security

- A worktree path cannot rescue unrelated destructive operations.
- An allowed temporary deletion cannot rescue a second destination outside
  its declared scope. Check every operand and reject ambiguous syntax.
- Test flag order, whitespace, shell separators, quoted arguments and paths.
  Preserve ordinary safe commands and explicitly supported cleanup paths.
- Keep personal environment restrictions out of generic built-in policy;
  provide a supported policy mechanism if needed for environment-specific bans.

### C — Recovery

- Distinct sources with the same basename survive backup and restoration.
- Preserve links as links, record source identity and detect incomplete
  backups. Compatibility with existing backup layouts must be explicit.
- Exercise the actual rollback consumer, including directory/file collisions
  and failure after partial progress. All fixtures stay in temporary paths.

### D — Curated memory

- The SessionStart hook includes a sentinel from canonical `MEMORY.md` and
  episodic context on supported adapters, without cross-project retrieval.
- Missing/unreadable memory degrades visibly and safely. Bound its contribution
  and preserve existing section priorities intentionally.
- Report the actual source and delivery result; do not claim native loading
  without a consumer-level probe.

### F and E — Diagnostics and effective configuration

- Doctor can inspect an existing read-only metrics database without changing
  its journal/schema or aborting unrelated sections.
- Selftest distinguishes product failure from an unverifiable environment.
- Show each profile's selected agent, declared hooks, effective hooks,
  exclusions, unavailable signals/operations, and defaults suppressed by an
  explicit scripts list. Reuse existing resolution functions.
- Separate configuration evidence, persisted trust records and observed hook
  execution; do not report a stored hash as proof of execution.

### H — Context budget

- Inventory the global plus repository contract loaded for a given profile
  and cwd, while naming additional dynamic/skill/tool costs as unknown unless
  measured. Do not label byte estimates as measured model tokens.
- Capture an initial-turn/subsequent-turn comparison when a transcript exposes
  the necessary fields. Scope and sampling limits accompany every measurement.
- Prepare a concrete instruction-pruning proposal with preserved safeguards.

### I — Proposal lifecycle

- List retained proposals and allow explicit reviewed requeue without losing
  source records, duplicating proposals or bypassing the pending cap.
- Use locking/atomic writes consistent with existing consumers; test retry and
  partial failure. Do not auto-accept or expire personal rules.
- Record the live baseline separately from fixtures: 143 pending proposals in
  18 projects, 13 at/above cap 10; 21 held rows in five projects at audit time.

### J and G — Fleet and instruction coherence

- Distinguish active managed repos, deliberate migration deferrals, upstream
  checkouts and instruction files stored as data. Exceptions are explicit and
  narrowly scoped; ancestor shadows remain detectable.
- Validate skill/command references against each profile's effective assets.
- Reconcile memory-loading claims, runtime-specific edit instructions and
  environment-specific command permissions with tested behavior.
- Prepare managed configuration changes with chezmoi source ownership checked.
  Do not trigger implicit commit/push of unrelated dotfiles changes.
- Preserve the existing Wave 1 observation period and deferred work rollout.

### K and L — Verification and adoption

- Measure current gate duration by category; inspect concurrent pruning work
  before proposing overlapping changes. Keep mandatory gates unchanged until
  an alternative has evidence and a concrete reviewable policy change.
- Define baseline, adoption horizon, outcome metric and removal threshold for
  relevant behavioral automation. Do not fabricate retrospective measurements.
- Keep the Graph Assist calibration unchanged until its current window closes.

#### Behavioral automation adoption review

Record intervention exposure, agent action and task outcome separately. A hook
invocation or tool call demonstrates reachability, not a better task result.
Use the same eligible population and profile/project scope before and after
activation. Report numerator, denominator, missing data and sample size; if
outcomes cannot be observed, mark the decision inconclusive and do not widen
the trigger to manufacture adoption.

| Surface | Baseline and horizon | Outcome and harm | Decision and reversal |
| --- | --- | --- | --- |
| Automatic memory suggestions (scoped QMD suggestions and proposal notices, evaluated separately) | Record the first eligible-session exposure and a pre-activation or disabled-profile comparison where available; historical acceptance and task benefit are unknown. Review after four weeks of observed exposure. | Review at least 20 exposed eligible sessions per trigger for relevance and correct task use; count wrong-project suggestions, stale or duplicate rules, and displaced higher-priority context. Queue size and accepts alone are workflow counts. | Proposed: remove a trigger if fewer than half of reviewed exposures are relevant or any confirmed cross-project disclosure occurs. If fewer than 20 exposures exist at week four, allow one frozen two-week extension; retire the trigger if still under 20 at week six. Keep proposal sources and explicit review CLI. |
| SessionStart context injection | Inventory effective static sources and body limits per profile/cwd before rollout, after consumer validation; byte totals are not model tokens. Review after four weeks on the same eligible task population. | Sample source receipt and whether the agent made a correct decision that required that source; record critical-section displacement, wrong source, truncation and measured startup latency. Token usage totals do not isolate injection savings. | Proposed: remove or narrow a section if no attributable useful cases are observed in at least 20 eligible reviewed sessions, or any confirmed wrong-project content is delivered. Revert only the section/config entry, preserving canonical memory and existing bounds until its own consumer check passes. |
| Goal/verification reminders | Preserve the existing 17% (29/169 graded sessions) baseline and the four-week window ending 2026-10-08 for the goal prompt. The Stop reminder needs its own eligible `/goal` denominator; no historical reminder-success rate exists. | Compare goal declarations on graded sessions, then audit whether verification evidence supports the stated criterion. Track `verify_block`, `verify_ran`, `verify_skipped`, unsupported adapters and repeated/noisy reminders separately. `verify_ran` records invocation, not adequacy. | Apply the existing goal-prompt kill rule: remove its injection if the graded-session declaration rate fails to exceed 17% or sampled signal-to-noise is below 50%. Proposed for the Stop reminder: remove its hook if fewer than half of eligible first blocks lead to adequate verification, or it blocks after adequate verification; retain the independent verification skill. |

For each review, record the deployed revision, exposure start, eligible sessions,
source/query for counts, a small blinded transcript audit of task outcomes,
and any unavailable fields. Avoid joining separate hook and transcript events by
timestamp alone; use session and profile identity. A missing denominator is an
unknown verdict, not zero adoption. Minimal missing instrumentation is one
deduplicated exposure/disposition record per session and surface, plus a
sampled outcome audit; these are future measurements, not shipped counters.
Reuse `loop_events`, proposal dispositions, context
budget inventory and transcript readers before adding a new metrics store.

Graph Assist remains on its existing 2026-09-25 day 0, 2026-10-09 day 14,
and frozen graph-touch, Hit precision (completeness) and latency kill thresholds.
Its report is evaluated independently; this review neither restarts nor
recalibrates it.

## Local implementation record

The following reviewed lane commits are integrated into the local review branch.
Publication, installation and live profile changes remain separate steps.

| Unit | Lane commit | Delivered scope |
| --- | --- | --- |
| A | `b31945a0` | Identity refusal, exact session scope and scoped QMD suggestions |
| B | `3624abf8` | Operation-scoped cleanup policy and explicit command denial |
| C | `2c0059bf` | Indexed backup manifest and verified rollback |
| D | `ef74c4d7` | Bounded canonical memory hook delivery |
| F | `a97172ed` | Read-only metrics diagnostics and partial-failure reporting |
| E | `2f9279e7` | Effective profile inspection with native wiring evidence |
| J | `526db36b` | Explicit fleet exceptions preserving active instruction shadows |
| I | `572132dc` | Selected held-proposal recovery, locking and durable disposition |
| H | `b86c8f26` | Selected static-source inventory with explicit measurement limits |

G supplies private candidate source patches validated on copied profiles;
they are intentionally outside this public repository. K retains all four gates:
existing timing and pruning evidence does not justify a policy reduction.
L supplies the prospective review criteria above; no new exposure instrumentation
or changed experiment calibration is claimed.

F disclosed that two review corrections preceded their regression tests.
Subsequent negative controls failed without each fix and passed after restoration;
this establishes test sensitivity, not retrospective compliance with strict TDD.

## Integration and completion

Review each diff and evidence independently. Re-run targeted reproductions
against the worker's committed revision, then run all four gates on the final
integration revision before committing it. Never infer success from pane state.

Retain worktrees until their changes are integrated and cleanup is verified.
Report local commit IDs, validation results, unresolved design decisions and
the exact release/install/configuration actions still needed. A unit is not
complete merely because its agent wrote a report or passed an isolated test.
