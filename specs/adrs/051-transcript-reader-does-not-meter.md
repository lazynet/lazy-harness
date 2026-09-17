# ADR-051: The `TranscriptReader` Protocol does not carry what metering needs

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-012 (SQLite monitoring), ADR-032 (agent adapter completeness), ADR-037 (metric event v2), ADR-048 (Codex rollout streams)

## Context

Decision 2 of `specs/designs/2026-09-13-multi-agent-blast-radius-design.md`
(`:374-453`) points `ingest` at the directory the profile's own agent declares,
and deletes the `or "projects"` fallbacks. It is explicit that this is only half
the job: *"Ingest still cannot parse a non-Claude transcript — that is
`TranscriptReader`, and it stays at step 12. Decision 2 only ensures that when
the reader lands, ingest is already pointed at the right directory."*

Step 12 has since landed. `ClaudeCodeAdapter` and `CodexAdapter` both implement
`TranscriptReader`, both yield `Signal.TOKEN_USAGE` events carrying a
`TokenUsage`. So the question decision 2 deferred is now answerable, and it has
two halves:

1. Does `ingest` drop its hand-written parser (`monitoring/collector.py`
   `iter_assistant_messages`) and read Claude Code through `read()` too?
2. Does `ingest` meter Codex through `CodexAdapter.read()`?

Both were treated as one question — "is the reader at parity with the parser" —
and measured before either was decided.

## The measurement

A throwaway script ran both paths over every Claude Code transcript on the
development host — **2,619 files, 102,464 usage records** — and compared numbers
only. Nothing from those transcripts is reproduced here or anywhere in this
repository.

**The token counts are identical.** Summed across every file both paths locate:

| Bucket | Hand parser | `read()` |
|---|---|---|
| input | 250,907 | 250,907 |
| output | 101,997,328 | 101,997,328 |
| cache read | 18,402,800,832 | 18,402,800,832 |
| cache create | 452,506,245 | 452,503,605 |

2,618 of 2,619 files agree on all four buckets; both paths emit exactly 102,464
usage records. So the reader is *correct as far as it goes*, and none of what
follows is a defect in it.

**Four things it does not go far enough to answer.** Each is a dimension
`session_stats` requires, not a nicety:

- **Model — 6 distinct values from the parser, 0 from the reader.**
  `TranscriptEvent` has no model field and `TokenUsage` has no model field, so
  nothing `read()` yields names the model. `session_stats` is
  `UNIQUE(session, model)` and `calculate_cost` is per model: without it there
  is no row key and no price.
- **Message id — 102,464 from the parser, 0 from the reader.** Cross-file
  dedup is property 1 of `monitoring/ingest.py`'s own docstring: `/resume`
  writes a new JSONL re-including the prior conversation, and the shared prefix
  is double-counted without a stable `message.id` to attribute to the oldest
  file. `TranscriptEvent.tool_use_id` pairs a tool call with its result and is
  `None` on a usage event; there is no message id.
- **Cache TTL split — 2,160 of 2,619 files carry non-zero 1-hour cache writes.**
  `TokenUsage` has one `cache_creation_tokens`. `split_cache_creation` keeps
  5-minute and 1-hour writes apart because they are **priced differently**;
  collapsing them is a wrong price, not a lost detail.
- **`memory/` exclusion — `locate_sessions` yields 17 files the parser
  excludes, all of them under a `memory/` ancestor.** Those are user-owned
  episodic logs (`decisions.jsonl`, `failures.jsonl`), not agent transcripts.
  `locate_sessions` globs `**/*.jsonl` and has no reason to know that; ingest
  does.

**A fifth finding, incidental and worth recording.** `split_cache_creation`'s
docstring says that across 6,642 measured assistant messages the `cache_creation`
breakdown and the `cache_creation_input_tokens` total "always agree". Over
102,464 messages they disagree in **4 messages in 1 file, by +2,640 tokens**
(breakdown above total). That is the whole of the one-file cache-create
discrepancy in the table. The parser trusts the breakdown, which remains the
documented and correct choice; only the universality of the claim is false.

## Decision

**The hand parser stays, and Claude Code is not moved onto `read()`.** There is
no parity to act on: the reader answers one of the five questions ingest asks a
transcript.

**Codex is not metered through `CodexAdapter.read()` either**, for the first of
those reasons. Codex's rollout does carry a model — `turn_context` has it
(`specs/designs/codex-evidence.md` §5.2) — but that kind is deliberately not
emitted, and `TranscriptEvent` has no field to emit it into. Reaching into
`TranscriptEvent.raw` is not an option the contract allows: it is documented
*"Adapters only"*, and a consumer parsing `raw` is the hand-written parser
again with none of its tests.

**What ingest does instead** is refuse, visibly. `ingest_profile` skips a
profile whose agent writes a dialect its parser was not written for, and
`lh doctor`'s Transcripts section reports the profile. The alternative — walking
a Codex rollout with Claude Code's parser — finds zero `type: "assistant"` lines
and reports the profile *empty*, which is indistinguishable from a profile that
did no work. That is the fail-open shape decision 2 exists to delete.

**A pseudo-model was rejected.** `is_pseudo_model` exists for `<synthetic>`, and
its docstring is explicit that the reason $0 is correct there is that those
messages *consumed no tokens*. A Codex row would consume millions and report
$0 — merging "free" with "unknown", which is precisely the distinction
`TokenUsage`'s own docstring refuses when it makes every field `int | None`
("a provider that reported no cache field and a turn that cached nothing are
different facts, and a 0 merges them into the second"). A wrong number that
reaches sinks and totals is worse than a named gap.

## What would change the decision

One Protocol change, in `agents/base.py`, which this ADR does not make — that
file is owned elsewhere this wave and the change should land with its own tests:

```python
@dataclass(frozen=True)
class TranscriptEvent:
    ...
    model: str | None = None
    """token_usage / messages: the model that produced the turn, as the
    provider names it. `None` where the transcript does not disclose it."""
    message_id: str | None = None
    """The provider's own stable id for the turn, where it has one. Distinct
    from `tool_use_id`, which pairs a call with its result."""
```

and on `TokenUsage`, a `cache_creation_1h_tokens: int | None = None` so the
TTL split survives the crossing. Appended with defaults, which is the mechanism
ADR-037 established for `MetricEvent` and which keeps every existing reader
valid.

With those three fields, `ClaudeCodeAdapter.read()` answers four of the five and
`CodexAdapter` gains a reason to emit `turn_context`. The fifth — the `memory/`
exclusion — belongs to ingest either way, since it is a statement about what
this harness writes under an agent's directory and not about the agent.

## Consequences

- Two paths parse Claude Code's transcript: `read()` for hooks, the hand parser
  for metering. They are held to the measured agreement by
  `tests/unit/test_transcript_reader_parity.py`, which asserts both the
  equality (token totals) **and** the four documented differences. A change
  that narrows or widens either one fails that test, so this ADR cannot go
  stale quietly.
- Codex sessions are visible and unmetered. `lh doctor` reports the profile as
  having a reader; `lh metrics` has no rows for it. The two surfaces do not
  contradict each other because the Transcripts verdict is worded about the
  *reader*, not about ingest.
- `monitoring/ingest.py` carries `_PARSED_DIALECT = "claude-code"`, a registry
  key where a capability query belongs. Nothing in `AgentAdapter` answers "what
  dialect is your transcript", and `TranscriptReader` says a reader exists, not
  that its events carry what a given consumer needs. The constant is the honest
  shape of that gap and is deleted by the Protocol change above.
