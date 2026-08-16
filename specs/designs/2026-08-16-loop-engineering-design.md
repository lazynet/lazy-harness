# Loop engineering: goal-driven execution, recurring loops, and the outer loop

**Status:** proposed
**Date:** 2026-08-16

## Problem

The harness is mature at the *environment* layer — hooks, memory, skills, deployment — and has an incipient *topology* layer in dynamic workflows. What it lacks is the layer between them: the **feedback cycle**. Sessions execute, but nothing forces them to declare what success looks like before starting, or to prove it was reached before stopping.

Three symptoms, all observed rather than hypothesised:

1. **Sessions stop before the work is actually done.** A successful edit is treated as a completed task. The repo's own `CLAUDE.md` already carries a verification-gate list built from repeated failures of exactly this kind, but it is a per-repo reminder, not a mechanism.
2. **Recurring work is re-prompted by hand.** Vault maintenance, proposal drainage, PR babysitting, and coherence audits are all well-defined recurring streams that are triggered manually each time.
3. **The outer loop does not close.** `compound_loop.py` writes `claude-md` proposals every session, but nothing drains them. At the time of writing, 23 proposals are pending, the oldest three days old. The loop that is supposed to make the harness learn is the loop that is stalled.

## Evidence

### From the knowledge base

Six independent sources converge on one skeleton — **Act → Observe → Evaluate → Adjust** — and agree that the value sits in the last two steps, which an agent does not perform unprompted.

| Source | Contribution |
|---|---|
| Claude Code team, *Getting started with loops* | Taxonomy of four primitives — turn-based, goal-based, time-based, proactive — classified by trigger, stop condition, and primitive used |
| *20 Loop Design Patterns* | Separate the generator from the evaluator. A model is a poor judge of its own output |
| Steinberger / Cherny, *WTF is a loop* | Three mandatory hard stops: iteration ceiling, no-progress detection, budget |
| Karpathy-derived `CLAUDE.md` guidelines | Goal-Driven Execution: declarative success criteria outperform imperative instructions |
| Morris (Fowler), *Humans and Agents in Loops* | "On the loop": when something fails, improve the harness that produced it, not the artifact |
| *Self-improvement loop for Skills* | An inner loop executes; an outer loop observes the inner loop and edits the skill |

### From the harness itself

Three pending compound-loop proposals already state the design constraints for this work:

- **#2** — a soft rule in `CLAUDE.md` (documented practice without enforcement) should be expected to see ~60% non-compliance. Critical rules need hook or context-injection enforcement to approach 0%.
- **#9** — before shipping automatic behaviour, audit by measurement whether the mechanism drives adoption after N sessions. Zero observable impact means deprecate, not add alternate triggers.
- **#15** — request-injecting automation must verify that the execution mechanism is reachable, that adoption is non-zero after a four-week window, and that signal-to-noise exceeds 50%.

The design below treats these as binding.

### What already exists

Verified against the installed Claude Code (2.1.232) and the deployed profile:

- `/goal <condition>` is native: *"Set a goal Claude checks before stopping"*, with `/goal active` and `/goal clear`. A string in the binary (`"/goal can't run while hooks are restricted"`) indicates it is implemented through the internal hook chain.
- `/loop` and `/schedule` ship as skills; `CronCreate` is available as a tool.
- `UserPromptSubmit` carries no first-party hook in the deployed profile — the injection point for phase 1 is free.
- `monitoring/db.py` provides SQLite with an established idempotent-migration pattern, but `session_stats` is token/cost oriented. Adoption measurement needs a new table.

The consequence for scope: **most of the mechanism already exists.** This is a wiring-and-discipline problem, not a construction problem.

## Non-goals

- Reimplementing `/goal`. A durable `goal.json` artifact was considered and rejected: it duplicates a native primitive for portability that is not needed today.
- Hard-blocking session close. Phase 1 ships soft enforcement and escalates only on measured data (see kill criteria).
- LLM-based prompt classification. The `UserPromptSubmit` hook runs on every prompt and must stay deterministic and cheap.
- Growing `CLAUDE.md` by more than ~15 lines. The file is already near 200 lines; context rot degrades agent quality past roughly 60% window utilisation, so doctrine belongs in skills and hooks, not in always-loaded text.

## Design

### Phase 0 — Instrument before injecting

Add a `loop_events` table to `monitoring/db.py`, following the existing `_migrate_identity_columns` idempotent pattern:

```sql
CREATE TABLE IF NOT EXISTS loop_events (
    session   TEXT NOT NULL,
    ts        REAL NOT NULL,
    project   TEXT NOT NULL DEFAULT '',
    profile   TEXT NOT NULL DEFAULT '',
    kind      TEXT NOT NULL,
    detail    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_loop_events_session ON loop_events(session, ts);
```

`kind` is one of `goal_declared`, `goal_absent`, `verify_ran`, `verify_skipped`, `session_closed`. Surfaced through `lh metrics loops`.

This phase ships **with zero user-facing friction** and runs for two weeks to establish a baseline: in what fraction of non-trivial sessions is a success criterion declared at all. The expected answer is near zero, but proposal #9 makes the measurement a precondition, not an afterthought — without a baseline there is no way to tell later whether the enforcement worked or merely added noise.

### Phase 1 — Goal-driven execution and verification

**Skill `verify-before-done`.** The single highest-value piece, and the only one that pays off independently of everything else. It encodes quantitative checks per work type rather than a generic reminder:

| Work type | Mandatory verification |
|---|---|
| Code | tests executed **with output shown**, lint, build |
| Config / hooks | reload the file, invoke the **installed** binary (never the development runner) |
| Docs | strict docs build passes |
| Infrastructure | second playbook run reports zero changed |

The governing rule: a task is never reported complete on the strength of a successful edit. This generalises a verification gate the repo already carries and makes it executable.

**Hook `user_prompt_goal.py` on `UserPromptSubmit`.** Deterministic classification of the incoming prompt — length, action verbs, file references. When the work looks non-trivial and no goal is active, it injects a request for a verifiable success criterion through `additionalContext`. It never blocks, and it records `goal_declared` or `goal_absent`.

**Separate evaluator.** A subagent on the cheapest capable model receives the declared criterion plus the collected evidence and rules on whether the criterion was met. It is invoked from the skill, not from a hook: hooks cannot spawn subagents.

**Soft enforcement on `Stop`.** A hook cannot call a subagent, but it can return `decision: "block"` with a `reason`, handing control back with instructions. Phase 1 uses this once per session: if the session declared a goal and no `verify_ran` event exists, the first stop attempt returns a reminder; the second closes regardless. The event is recorded either way.

The division of responsibility is deliberate: **the hook is the guard, the skill is the procedure, the subagent is the judge.**

### Phase 2 — Recurring loops (no new code)

Inventory the streams currently prompted by hand — proposal drainage, vault maintenance, weekly review, PR babysitting, coherence audits — and move each to `/schedule` (persistent) or `/loop` (local, session-lived).

Two rules from the sources apply without exception:

- Never run a routine more often than the thing it watches changes.
- Every autonomous loop carries three caps from day one: iteration ceiling, no-progress detection, and a token budget.

### Phase 3 — Closing the outer loop

`compound_loop.py` already writes proposals; the gap is drainage. Two changes:

1. **Cadence pressure.** When pending proposals exceed 10, `context_inject.py` promotes the notice from a marginal line to a soft block at session start.
2. **Compression.** When the project memory index approaches its 200-line ceiling, the outer loop consolidates existing entries instead of appending — the memory-compression pattern, which the current implementation lacks.

The existing backlog is drained manually, highest index first, before the cadence rule is enabled.

## `CLAUDE.md` delta

At most ~15 lines: a table mapping work shape to loop primitive, and the goal-driven rule. Everything else lives in skills and hooks, where it costs no context until invoked.

## Success criteria

Measured from `loop_events`, four weeks after phase 1 ships:

- Success criteria declared in **>60%** of non-trivial sessions (baseline expected near 0%).
- Verification runs in **>80%** of sessions that declared a goal.
- Injection signal-to-noise **>50%** — the fraction of injections on prompts that genuinely were non-trivial work.

## Kill criteria

Binding, per proposal #15. If at four weeks adoption is zero, or signal-to-noise is below 50%, the `UserPromptSubmit` injection is **removed** rather than supplemented with additional triggers. The `verify-before-done` skill survives independently; it has value with or without the hook.

## Risks

| Risk | Mitigation |
|---|---|
| Injection becomes noise on every short prompt | Deterministic classifier tuned conservatively; phase 0 baseline shows how often it would have fired before it fires |
| Soft block turns into a nag that gets ignored | Fires once per session, never twice; escalation to hard block requires data, not intuition |
| Phases ship as one large change and none lands | Each phase is independently shippable and independently valuable; phase 1's skill works alone |
| The evaluator subagent adds cost per session | Cheapest capable model, invoked once at verification time, not per turn |

## Sequencing

Phase 0 → phase 3 (manual drainage, no code) can run in parallel → phase 1 → measure four weeks → phase 2. Phase 1 does not begin until phase 0 has a baseline.
