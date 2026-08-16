# Loop engineering: goal-driven execution, recurring loops, and the outer loop

**Status:** proposed
**Date:** 2026-08-16

## Problem

The harness is mature at the *environment* layer — hooks, memory, skills, deployment — and has an incipient *topology* layer in dynamic workflows. What it lacks is the layer between them: the **feedback cycle**. Sessions execute, but nothing forces them to declare what success looks like before starting, or to prove it was reached before stopping.

Three symptoms, all observed rather than hypothesised:

1. **Sessions stop before the work is actually done.** A successful edit is treated as a completed task. The repo's own `CLAUDE.md` already carries a verification-gate list built from repeated failures of exactly this kind, but it is a per-repo reminder, not a mechanism.
2. **Recurring work is re-prompted by hand.** Vault maintenance, proposal drainage, PR babysitting, and coherence audits are all well-defined recurring streams that are triggered manually each time.
3. **The outer loop does not close.** `compound_loop.py` writes `claude-md` proposals every session, but nothing drains them. At the time of writing, 23 proposals are pending, the oldest three days old. The loop that is supposed to make the harness learn is the loop that is stalled.
4. **Cross-repository delegation is invented from scratch every time.** When a session needs work from a sibling repository before it can continue, the pattern — open a pane, start an agent there, keep working on the independent half, wake on completion — has to be described by hand each time. Nothing suggests it, and the topology it needs does not match the one command that exists.

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
- `herdr_context_gauge.py` exposes `context_tokens(transcript) -> int | None`, already used to publish a live per-pane context reading. Phase 4 reuses this function rather than building a second sensor.
- The `/herd` command (162 lines) plus the upstream `herdr` skill it invokes (195 lines) load 357 lines of context whenever parallel work is considered. Actual usage in the observed session was five CLI commands.

The consequence for scope: **most of the mechanism already exists.** This is a wiring-and-discipline problem, not a construction problem.

## Non-goals

- Reimplementing `/goal`. A durable `goal.json` artifact was considered and rejected: it duplicates a native primitive for portability that is not needed today.
- Hard-blocking session close. Phase 1 ships soft enforcement and escalates only on measured data (see kill criteria).
- LLM-based prompt classification. The `UserPromptSubmit` hook runs on every prompt and must stay deterministic and cheap.
- Automatic *invocation* of Herdr. Phase 4 makes the harness suggest delegation; the user still triggers it. The upstream skill's self-suppressing description is respected, not forked.
- Changing `/herd`. Phase 4 adds a second, differently-shaped pattern beside it.
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

### Phase 4 — Cross-repository delegation

#### Why this is not the existing command

`/herd` fans a written plan out to N workers in worktrees of the **same** repository, and its output is commits. Cross-repository delegation is a different topology: one agent in a **different** repository, an asynchronous dependency that blocks the caller halfway, and an output the caller needs in order to continue. The caller keeps working on the independent half rather than orchestrating.

They share a CLI and nothing else. Phase 4 adds a second pattern; it does not modify `/herd`.

#### Reversal of a prior decision

The 2026-08-06 herd orchestration design recorded `Trigger → Manual slash command. No automatic invocation.`, reasoning that because the trigger was manual, the upstream skill's self-suppressing description did not matter and no `CLAUDE.md` nudge was needed.

Phase 4 reverses that decision on the strength of ten days' usage: the pattern proved valuable and recurring, but it never fires unless described by hand. The reversal is scoped — automatic **suggestion**, never automatic invocation. The agent proposes; the user still triggers.

#### Skill `delegate-cross-repo`

Roughly 40 lines covering the five commands the pattern actually uses — pane split, agent start, agent prompt, background monitor, pane read — plus the two things that are not guessable:

- **`pane read` blocks against an alternate screen.** When a larger `--lines` reveals nothing more, rows have left the alternate screen and cannot be recovered from scrollback. Fall back to asking the delegate to write its full response to a file and reply with only the path. Do not request file output in the initial prompt.
- **Cross-check before closing.** Staged or uncommitted work in the target repository can silently contradict the design the caller just produced. Check for it explicitly rather than assuming the delegate's answer is the whole story.

Two procedural rules the observed session got right and that a naive implementation misses: send the **evidence** inside the requirement rather than only the conclusion, and advance the independent half while waiting instead of blocking on the delegate.

The upstream `herdr` skill stays installed and is invoked only when unusual CLI syntax is genuinely needed.

#### Pane lifecycle

One pane per task. A delegate pane is closed when its task completes; a new task opens a new pane rather than re-prompting the existing one. Re-use accumulates two things, not one: context tokens, and the prior task's framing. Fresh context per unit of work is the canonical loop shape.

The cost is real — agent startup defaults to a 30-second timeout, paid per delegation instead of once. Accepted: a delegate carrying three tasks' worth of context answers the third one worse than a cold one would.

**Ownership.** The upstream skill forbids closing panes the session did not create. Cleanup is therefore scoped to panes this session opened, never to every open pane — unrelated user panes routinely share the workspace. This requires a registry: `loop_events` records `delegate_pane_opened` with the pane ID in `detail`, and `delegate_pane_closed` on teardown. Open-minus-closed for the current session is the set eligible for cleanup.

**Liveness.** A pane is closed only in `idle` or `done`. In `working` or `blocked` it is left alone and reported. `unknown` is explicitly not a completion signal — the upstream skill states it "does not prove completion" — so it is treated as live, not as finished.

**Session teardown.** `session_end.py` already fires exactly once on shutdown and exits 0 on every path. It gains a step that closes this session's eligible panes and reports anything left running rather than forcing it.

**Orphans.** `SessionEnd` does not run when a session dies abnormally, so registered panes can outlive their owner. Before opening a new delegation, panes registered to sessions no longer alive are closed. This keeps the accumulation the one-pane-per-task rule exists to prevent from returning through the failure path.

#### Triggers

Both are evaluated in the same deterministic pass already performed by `user_prompt_goal.py`. Neither fires unless `HERDR_ENV=1`.

1. **Multi-repository signal.** The prompt names a known repository other than the working directory's, or references absolute paths outside it. The known-repository set is enumerated once and cached.
2. **Context above threshold.** Reuses `context_tokens()` from `herdr_context_gauge.py`. Default threshold is 60% of the effective window — the point at which the harness-engineering literature reports context rot degrading agent quality. Configurable.

Trigger 2 fires at most once per session and only when separable work is actually present; a high context reading with nothing to split off is a reason to compact, not to delegate. Suggesting delegation on context alone would be noise.

Enforcement matches phase 1: soft, once per session, recorded either way. New `loop_events` kinds: `delegate_suggested`, `delegate_accepted`, `delegate_declined`, `delegate_pane_opened`, `delegate_pane_closed`.

## `CLAUDE.md` delta

At most ~20 lines: a table mapping work shape to loop primitive — including which of `/herd` and cross-repo delegation fits which topology — and the goal-driven rule. Everything else lives in skills and hooks, where it costs no context until invoked.

## Success criteria

Measured from `loop_events`, four weeks after phase 1 ships:

- Success criteria declared in **>60%** of non-trivial sessions (baseline expected near 0%).
- Verification runs in **>80%** of sessions that declared a goal.
- Injection signal-to-noise **>50%** — the fraction of injections on prompts that genuinely were non-trivial work.

For phase 4, measured separately:

- Delegation suggestions accepted **>40%** (`delegate_accepted` over `delegate_suggested`). Below that the trigger is guessing.
- Context loaded for a delegation drops from 357 lines to under 60.

## Kill criteria

Binding, per proposal #15. If at four weeks adoption is zero, or signal-to-noise is below 50%, the `UserPromptSubmit` injection is **removed** rather than supplemented with additional triggers. The `verify-before-done` skill survives independently; it has value with or without the hook.

The same applies per trigger in phase 4: the multi-repository signal and the context-threshold signal are measured and killed independently. One failing does not condemn the other, and neither is rescued by adding a third.

## Risks

| Risk | Mitigation |
|---|---|
| Injection becomes noise on every short prompt | Deterministic classifier tuned conservatively; phase 0 baseline shows how often it would have fired before it fires |
| Soft block turns into a nag that gets ignored | Fires once per session, never twice; escalation to hard block requires data, not intuition |
| Phases ship as one large change and none lands | Each phase is independently shippable and independently valuable; phase 1's skill works alone |
| The evaluator subagent adds cost per session | Cheapest capable model, invoked once at verification time, not per turn |
| The thin delegation skill drifts from the upstream CLI | It documents the pattern and its two gotchas, not the CLI surface; the upstream skill remains the syntax authority and is invoked when needed |
| Delegation suggestions fire outside Herdr and read as broken | Both triggers gate on `HERDR_ENV=1` before evaluating anything |
| Context-threshold trigger nags without anything to delegate | Fires once per session, and only when separable work is present |
| Cleanup closes a pane the user owns | Only panes registered as opened by this session are eligible; the registry is the authority, never the workspace listing |
| Cleanup closes a delegate mid-task | Close requires `idle` or `done`; `working`, `blocked` and `unknown` are all treated as live |
| Abnormal session death leaves orphan panes | Panes registered to dead sessions are swept before the next delegation opens |

## Sequencing

Phase 0 → phase 3 (manual drainage, no code) can run in parallel → phase 1 → phase 4 → measure four weeks → phase 2. Phase 1 does not begin until phase 0 has a baseline.

Phase 4 follows phase 1 rather than running beside it because it extends the same hook and the same soft-enforcement path. Its skill, however, is independent and can ship first if the delegation pattern is needed before the hook exists.
