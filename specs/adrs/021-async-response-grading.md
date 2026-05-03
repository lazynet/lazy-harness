# ADR-021: Async response grading via the compound-loop worker

**Status:** accepted
**Date:** 2026-05-02

## Context

The compound-loop worker (ADR-008) extracts decisions, failures, learnings, and handoff items from finished sessions. Today it has no notion of *quality*: every session is treated as equally signal-rich. Real sessions vary widely — some end with the agent succeeding cleanly, others with the agent hallucinating, repeating tool calls, or silently giving up.

Without a quality signal we cannot:

- prioritize which sessions deserve a follow-up ticket
- detect regressions in the harness (a steady drop in average quality)
- distinguish "session ended OK" from "session ended in failure" when planning the next one

A separate grading pipeline (extra LLM call, separate queue) was considered and rejected: it doubles infra and the existing worker already invokes a headless Claude with the full transcript.

## Decision

Extend the **same** `claude -p` call the worker already makes to also return a `grade` object alongside the existing `decisions / failures / learnings / handoff` structure. Persist the grade to `memory/grades.jsonl`. No new queue, no new worker, no new prompt.

### Schema extension (additive)

The prompt's JSON output gains one field:

```jsonc
{
  "decisions":  [...],
  "failures":   [...],
  "learnings":  [...],
  "handoff":    [...],
  "grade": {
    "quality":    "excellent" | "good" | "acceptable" | "poor",
    "issues":     [...],   // fixed taxonomy, see below
    "reasoning":  "1-2 sentences",
    "confidence": 0.0-1.0
  }
}
```

`issues` is drawn from a fixed taxonomy:

- `incomplete` — assistant stopped before resolving the user's request
- `hallucination` — invented APIs / files / tools that don't exist
- `tool_misuse` — wrong tool, wrong arguments, repeated failed calls
- `missed_context` — ignored a relevant constraint stated earlier in the session
- `wrong_approach` — solved a different problem than the user asked
- `inefficient` — produced the right answer but with avoidable cost
- `none` — no issues observed (used when quality is `excellent` or `good`)

### Persistence

`persist_results` gains a `grades.jsonl` writer, parallel to `decisions.jsonl` and `failures.jsonl`. One line per session, append-only:

```jsonc
{
  "ts": "2026-05-02T15:30:00-03:00",
  "type": "grade",
  "session_id": "abcd1234-...",
  "project": "lazy-harness",
  "quality": "acceptable",
  "issues": ["inefficient"],
  "reasoning": "Got there but ran ruff three times unnecessarily.",
  "confidence": 0.8
}
```

### Backlog escalation (PRJ.md update)

When `grade.quality` is `poor`, **or** `acceptable` with a non-empty `issues` list, the worker locates the matching `PRJ-<Name>/PRJ-<Name>.md` under the user's LazyMind vault and appends a backlog item under `## Pendiente — Alta prioridad`:

```markdown
- [ ] **Session quality regression — <reasoning>** (graded YYYY-MM-DD, session <short_id>, issues: <list>)
```

Resolution `cwd → PRJ-<Name>.md` is best-effort:

- Look up `<lazymind_dir>/1-Projects/PRJ-*/PRJ-*.md`
- Match by alias-or-title fuzzy-equal to `os.path.basename(cwd)`, with common prefixes stripped (`lazy-`, `flex-`, `mngt-`)
- If no match, log and skip — escalation is opportunistic, not required

`lazymind_dir` is a new optional field in `CompoundLoopConfig`. Default: probe `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/LazyMind`, fall back to `~/LazyMind`. Nothing is escalated if the probe fails.

## Alternatives considered

- **Separate grading worker / queue.** Rejected: doubles infra. The existing worker already has the full transcript, the prompt cache for the model, and an established producer/consumer split.
- **Multi-judge panel (Anthropic + OpenAI + Google).** Source: ["Self-Healing Agent Harness"](../../docs/...). Out of scope for v1 — overkill for a single-user tool. Single Haiku judge gives enough signal to prioritize tickets.
- **Synchronous grading inside the Stop hook.** Same UX-blocking objection as ADR-008 — rejected on principle.
- **Discrete categorical-router job (12 categories).** Same source. Reduced to 4 implicit categories (`coding`, `knowledge`, `planning`, `conversation`) tracked in `reasoning`. Not worth a separate prompt step in v1.
- **Grade every assistant turn, not the session.** Defer. The Stop hook is the only async-friendly insertion point today; per-turn grading would need a new event type. Re-evaluate when `PostMessage`-style events ship.
- **Auto-create PRs / Linear tickets on poor grade.** Out of scope. v1 only writes to the project's living readme, which is where the user will see it on the next session via `SessionStart`.

## Consequences

- **One LLM call, two pieces of signal.** No latency impact on session close (still async).
- **Backwards-compatible JSON.** Older worker code handling responses without `grade` keeps working; the field is optional in the parser.
- **Calibration risk.** ADR-008 warns that rewording the prompt degrades extraction quality. We mitigate by **appending** the `grade` block at the end of the schema, not interleaving, and by keeping the existing rules verbatim.
- **Privacy.** `grades.jsonl` lives in the same `memory/` directory as `decisions.jsonl` — same security profile (user-only, never synced unless the user puts the project under a synced path).
- **Backlog noise.** If the judge is too strict, every session leaves a backlog item. Counter-measure: only escalate `poor` or `acceptable + issues`. `good` and `excellent` never escalate. If even that proves noisy, the `confidence` threshold becomes a config knob.
