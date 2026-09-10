# Harness improvements — September 2026

**Status:** approved, in implementation
**Date:** 2026-09-10
**Supersedes:** nothing. Extends [`2026-08-16-loop-engineering-design.md`](2026-08-16-loop-engineering-design.md), whose phase 0 closes here.

## Why now

A review of ten vault articles published between 2026-08-29 and 2026-09-09 was
cross-checked against a month of measured usage rather than against intuition.
Three of the articles describe problems this harness demonstrably has; the rest
describe problems it does not, and those are named in "Out of scope" so nobody
re-derives them later.

### The measurements

September 1-10, both profiles, from `metrics.db` and the session transcripts:

| Model | Sessions | Cost | Cache read |
|---|---|---|---|
| `claude-opus-5` | 130 | $2985 | 4.15 B |
| `claude-sonnet-5` | 242 | $184 | 509 M |
| `claude-haiku-4-5` | 913 | $97 | 41 M |

- Global cache-read ratio **97.7%**. Prompt caching is not the problem and no
  work here targets it.
- Opus averages **32 M cache-read tokens per session** (max 248 M, single
  session $151). Cost is driven by turn count over a large context, not by
  model choice.
- **150 Agent tool calls in 873 sessions**, all `general-purpose`; zero
  `Explore`, zero `Plan`, zero `fork`. Bash was called 5046 times in the main
  thread.
- **5954 learnings, 100% `status: active`.** Nothing has ever been deprecated.
  August contributed 2959; September 1192 in ten days.
- `decisions.jsonl` carries two incompatible line schemas: older lines use
  `timestamp`/`fixed`/`deferred`, newer ones `ts`/`context`/`rationale`/
  `alternatives`. 4195 lines across 22 repositories.
- Largest always-loaded contracts: `lazy-popopen/CLAUDE.md` at 987 lines /
  70 KB, `lazy-ai-tools` 333, `lazy-ansible` 308, `lazy-desktop-manager` 223.
  `lazy-popopen` is the second most expensive project of the month at $409.
- QMD was queried 4 times in the month, against 8486 indexed documents.

### What the articles contribute

- *orchestrator-tax* separates tokens (paid once) from context (contaminates
  every subsequent turn). 5046 main-thread Bash calls is that failure mode
  measured.
- *subagent-context-modes* names a lever the harness never uses: `fork` for a
  worker continuing an investigation, isolated for a verifier that must judge
  without the supervisor's diagnosis.
- *memory-engineering-five-stage-pipeline* names the two stages the memory
  stack lacks: Reconcile and Decay.
- *fable-5-1* and *Nuevas reglas de context engineering para Claude 5* both
  put the ceiling for an always-loaded contract at ~200 lines, and both argue
  rigid rules should give way to judgement on frontier models.

## Architecture

Four tracks. Each is independently shippable and independently valuable; none
blocks another except where stated. Track 1 follows the division this repo
already uses for the goal sensor: **the hook is the guard, the command is the
measurement, the skill is the procedure.**

### Track 1 — Rightsizing the agent contract

**1a. Extend `pre_tool_use_memory_size` to cover `CLAUDE.md`.**
The hook already encodes the right ceilings — `MAX_LINES = 200`,
`MAX_BYTES = 12_000` — and already justifies why bytes matter more than lines.
Its scope predicate is a single `endswith("/memory/MEMORY.md")`. Widening it
to `CLAUDE.md` needs a second predicate and a separate threshold pair, because
the two files have different jobs: `MEMORY.md` is a curated index, `CLAUDE.md`
is a contract that loads on every session in every profile.

Thresholds are configurable under `[hooks.pre_tool_use]`. Defaults match the
literature: 200 lines, 12 KB. The hook stays a warning, never a block — a
contract that cannot be edited past a ceiling is worse than one that is too
long.

**1b. `lh memory rightsize`.**
Read-only. Lists every `CLAUDE.md` the harness can reach — profile contracts
plus the project keys already known to the memory stack — with line count,
byte count, and which threshold it breaches. Today there is no way to see the
fourteen files as one set; each is discovered only when someone edits it.

Resolution reuses `core/project_identity.py:project_key` rather than adding a
third resolver.

An earlier draft of this section called that function and
`hooks/builtins/_shared.py:project_key` duplicates to be reconciled. They are
not. The first returns a portable identity — `host/owner/name`, or
`local/<name>` with no remote; the second returns an absolute filesystem path.
Same name, different questions. The integration test that guards them asserts
they agree on *which directory is the project root* when called from a linked
worktree — the real failure this repo has hit — not that they return equal
values, which they never will.

**Discovery is by filesystem, not by memory.** Every `CLAUDE.md` under a
configured `[profiles.*].roots` enters the report. Presence in the knowledge
store is explicitly *not* a filter: a repository with no memory yet is a new or
lightly instrumented one, and those hold the contracts least likely to have
been pruned. Filtering on the store finds the files someone is already tending
and misses the abandoned ones — it inverts the command's purpose. This was
caught in review when the first implementation, which did filter that way,
omitted `lazy-popopen` — 987 lines, the file that motivated the track.

**1c. Skill `rightsize-claude-md`.**
Encodes the pruning criterion from *orchestrator-tax*, which is the part a
command cannot do: for each line, is this **a fact the agent is missing**, or
**a procedure the model would already follow**? Facts stay. Procedures move to
a skill or leave. A line whose deletion would cause no observable error is
deleted.

The skill runs `/claude-api prompt-audit` first, so anti-patterns are separated
from mere length before any judgement call is made.

**1d. Execute on four repositories.**
`lazy-popopen`, `lazy-ai-tools`, `lazy-ansible`, `lazy-desktop-manager`. One
session per repository, using the skill. This is the only track that touches
code outside this repo; `lazy-harness` supplies the tool, each repository
supplies its own commit.

### Track 2 — Closing the loop measurement

**2a. Phase 0 closed.** Done, committed 2026-09-10. The baseline is 17%
(29/169 graded sessions), and the phase 0 result section records why that is an
upper bound rather than an estimate: verdicts exist only for sessions the
compound-loop worker grades, which is 7.5% of non-trivial sessions and is
selected for length. The success criterion was restated against the denominator
that is actually computable, before the measurement window opens.

**2b. Phase 1.** Skill `verify-before-done` plus `[loops] inject_goal_prompt =
true`. Opens the four-week window against 17%. Kill criteria are frozen for its
duration.

**2c. `agent_dispatched`.**
A new `loop_events` kind, emitted by the compound-loop worker — which already
scans every session transcript — carrying model and `subagent_type` in
`detail`. Surfaced through `lh metrics loops` alongside the goal ratio.

This replaces phase 4 of the loop design rather than implementing it. Phase 4
measured Herdr pane delegation and gated everything on `HERDR_ENV=1`; the
measurement that matters is subagent dispatch, which happens in every session
and needs no external tool. Phase 4's `delegate_*` kinds stay unimplemented.

Baseline to record at ship time: 150 dispatches across 873 sessions.

**Why the worker and not a hook.** A `PostToolUse` hook would fire per dispatch
and could count directly, but it would also add a subprocess to the hot path of
every tool call. The worker already parses the transcript for grading and
insight capture; adding one more counter there costs nothing per session.

### Track 3 — ADR-040: Reconcile and Decay

The ADR declares the two missing pipeline stages and their contract. Both
commands follow `lh memory consolidate`: **propose-only by default, `--apply`
to write.** Neither resolves a conflict on its own — the article is explicit
that a system silently guessing which fact is current acts confidently on the
wrong one, and that marking a conflict beats resolving it blind.

**`lh memory decay`.** Marks learnings `status: superseded` when they have no
reference within a configurable horizon. Never deletes. 5954 files at 100%
active is the evidence that append-only without decay does not stay useful.

**`lh memory reconcile`.** Two detections, reported separately:
1. Schema drift within a `decisions.jsonl` — lines that do not share the
   current field set.
2. Decisions within one repository whose summaries contradict each other.

Detection 1 is deterministic and ships first. Detection 2 needs semantic
judgement and is the reason the command is propose-only.

### Track 1 result — pruned 2026-09-10

Seven contracts pruned, each verified independently against `wc` rather than on
the pruning agent's report. Over-threshold count went from 14/36 to 8/36.

| Repo | Before | After |
|---|---|---|
| `lazy-popopen` | 987 lines / 70.4 KB | 86 / 11.9 KB |
| `ydi-mgmt` | 347 / 18.1 KB | 166 / 11.1 KB |
| `lazy-ansible` | 308 / 15.3 KB | 193 / 11.1 KB |
| `tb-ydi-delivery` | 253 / 11.5 KB | 171 / 7.4 KB |
| `supervielle-mgmt` | 232 / 10.1 KB | 194 / 8.4 KB |
| `lazy-desktop-manager` | 223 / 16.5 KB | 157 / 10.4 KB |
| `lazy-ai-tools` | 333 / 23.9 KB | 194 / 12.6 KB |

Both profile contracts came down as a side effect: their weight is
`_common/CLAUDE.common.md`, shared, so pruning it once moved `lazy` from
12672 to 11530 bytes and `flex` from 12658 to 11516. Both are now under the byte
ceiling; both remain a few lines over 200.

**Where the pruning was deliberately stopped short.** `lazy-ai-tools` sits 579
bytes over the byte ceiling on purpose. Reaching it had cost three gotchas whose
failure mode is silence — a pass that never creates a project, `cache_*` being
`None` and never `0`, and the `--profile lazy` pin that makes a matched profile
distinguishable from a guessed one. They were restored. The size hook warns
rather than blocks precisely so a contract can make this trade.

The same reasoning applies to the three files left a few lines over 200 with
their bytes already under: the hook's own comment says the context window pays
for bytes, not newlines. Line count is the proxy; it is not worth spending a
gotcha on.

**One regression, caught and repaired.** The `ydi-mgmt` agent removed a
phase roadmap that existed nowhere else, leaving it only in git history. It said
so in its report rather than omitting it, and the content was restored to
`domains/estrategia/README.md` — the location the contract itself designates for
live domain state. This is the failure the skill warns about: deleting from one
place without creating in the other.

**Excluded on purpose.** The two `Archon` contracts (813 and 779 lines) belong
to an external open-source project; their contract comes from upstream and
pruning it would conflict on the next merge. The eleven contracts under
`ydi-data-layer/.worktrees/` are copies of one branch, and confirm the
command's worktree prune works.

## Out of scope

**The false-edge test for workflows.** The Workflow tool has zero uses, and
per the Google scaling paper that is the correct behaviour: multi-agent
degrades 39-70% on sequential tasks. There is nothing to fix. Adding a
criterion for workflows that are not used would be adding process — precisely
what track 1 exists to remove.

**Prompt caching work.** 97.7% cache-read ratio. Already solved.

**Herdr delegation (phase 4 of the loop design).** Superseded by 2c, which
measures the same lever without depending on an external multiplexer.

**Hard-blocking any of the new guards.** Every hook here warns. Escalation to a
block requires measured data, per the same rule that governs phase 1.

## Sequencing

```
2a (done) ──> 2b ──────────────> [4-week window]
1a ──> 1b ──> 1c ──> 1d
2c ──────────────────────────────> [baseline recorded]
3 (ADR-040 ──> decay ──> reconcile)
```

Tracks 1, 2c and 3 are independent and can run in parallel worktrees. 1d waits
for 1c because it uses the skill. 2b waits for nothing but should ship after 2c
so both measurements share a window.

## Risks

| Risk | Mitigation |
|---|---|
| The `CLAUDE.md` threshold fires on legitimately long contracts | It warns, never blocks, and the threshold is configurable per profile |
| `lh memory rightsize` re-implements project discovery and drifts | Reuses the existing resolver; an integration test asserts both callers agree |
| Pruning a `CLAUDE.md` deletes a genuine gotcha | The skill's criterion keeps facts and drops procedures; each repo's diff is reviewed in its own commit |
| `decay` marks a learning that was load-bearing | It marks `superseded`, never deletes; `--apply` is opt-in and the default run only proposes |
| `reconcile`'s contradiction detection produces noise | Ships after schema drift detection, which is deterministic; contradiction detection is propose-only from the start |
| `agent_dispatched` measures dispatch but not usefulness | Accepted. The baseline question is whether delegation happens at all; quality is a later measurement |
| Track 1d's four repositories drift back over time | 1a's hook is the ratchet — it fires on the next edit that crosses the ceiling |

## Success criteria

- `lh memory rightsize` reports zero repositories above threshold after 1d.
- `agent_dispatched` recorded for four weeks, with the 150/873 baseline
  documented at ship time.
- `lh memory decay --apply` run once, with the resulting active-learning count
  recorded.
- `lh memory reconcile` reports the `decisions.jsonl` schema drift that
  motivated it.

## Kill criteria

- **`CLAUDE.md` size hook:** if after four weeks it has fired only on files the
  user then chose to keep, the threshold is wrong. Re-calibrate once against
  the measured distribution, or remove the hook. Do not add a second signal.
- **`agent_dispatched`:** it is a sensor with no user-facing behaviour and
  cannot be "adopted" or fail. It is removed only if the counter proves
  unreliable against a hand count of transcripts.
- **`decay`:** if the first `--apply` run marks fewer than 5% of learnings,
  the horizon is too generous, not the stage unnecessary. Adjust once, then
  hold.
