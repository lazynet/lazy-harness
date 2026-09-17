# ADR-053: The `TranscriptReader` carries what metering needs, and ingest reads every agent through it

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** ADR-051
**Superseded by:** —
**Related:** ADR-012 (SQLite monitoring), ADR-032 (agent adapter completeness), ADR-037 (metric event v2), ADR-048 (Codex rollout streams), ADR-050 (metric event v3)

## Context

ADR-051 answered "does ingest meter Codex through `CodexAdapter.read()`" with
*no*, and it was right on the evidence it had. Measured over 2,619 real
transcripts and 102,464 usage records, `ClaudeCodeAdapter.read()` and
`collector.iter_assistant_messages` agreed on every token bucket to the token —
and the reader answered one of the five questions ingest asks a transcript. It
had no model, no message id, one cache-creation field where pricing needs the
5-minute/1-hour split, and `locate_sessions` yielded the `memory/` logs ingest
excludes.

That ADR did not leave the gap as an opinion. Its *What would change the
decision* section wrote out the Protocol change in full — three fields, appended
with defaults — and said the day `TranscriptEvent` gains a model, a test fails
and says so. `tests/unit/test_transcript_reader_parity.py` asserted each
difference as a `not hasattr(...)` tripwire so the decision could not go stale
quietly.

The tripwire has fired. This ADR reverses ADR-051's decision on exactly the
terms ADR-051 set, which is why it is a new record and not an edit: the earlier
reasoning was correct and is worth keeping, and only its premise expired.

The trigger is the iteration's own success criterion. `lh metrics ingest` has to
record events with `agent="codex"` — ADR-050 added the dimension, and a
dimension no row ever carries is a column, not a measurement.

## Decision

**Three fields cross the Protocol**, appended with defaults, the mechanism
ADR-037 established for `MetricEvent`:

```python
TranscriptEvent.model: str | None = None
TranscriptEvent.message_id: str | None = None
TokenUsage.cache_creation_1h_tokens: int | None = None
```

Every one is `None` when the provider does not disclose it, never `0` and never
`"unknown"`, for the reason `TokenUsage`'s own docstring already gives: a
provider that reported no cache field and a turn that cached nothing are
different facts.

`cache_creation_tokens` and `cache_creation_1h_tokens` are **siblings, not a
total and a share of it**. They are priced at different rates, so a consumer
wanting the whole write adds them. Where a transcript's breakdown disagrees
with its own total — 4 messages in 102,464, by +2,640 tokens — **the breakdown
wins**, which is the choice `collector.split_cache_creation` already documents.
Two paths pricing one turn must not resolve that case two ways.

**Both readers fill them.** Claude Code reads `model` and `message.id` off the
transcript line and carries them on every event that line yields, because the
model that produced a turn produced the tool calls in it.

Codex is the harder half, and it needs one thing no other reader does. No usage
record names the model; `turn_context` does, on an earlier line. So
`CodexAdapter.read()` carries the last model declared forward onto everything
that follows it — **the only backward reference in either reader**. That state
is a local of the read generator and never an attribute of the adapter:
`registry.py` builds a bare `cls()`, so one instance serves every profile and
two reads can be open at once. Held on `self`, the second would inherit the
first's model and bill one session's tokens under another session's name.

Reading `turn_context` does not violate ADR-048's one-stream-per-signal rule.
That rule exists because a rollout records the same fact in two streams;
`turn_context` duplicates nothing, and only one field of it is read.

For `message_id`, Codex's `response_id` is the key and `turn_id` is not:
measured over 176 records, `response_id` was a string on every one and unique
across all 15 rollouts, while those same 176 shared 21 `turn_id`s. Deduping on
the turn would drop every usage record in a turn but the first. Nothing in the
`response_item` stream carries `response_id` either — 0 of 176 matched an
item's `id` — so the two streams are not joined on it.

**Ingest reads every agent through its own reader.** The `_PARSED_DIALECT`
constant and its name comparison are gone, replaced by
`isinstance(agent, TranscriptReader)`. The refusal is unchanged in effect — a
profile whose agent cannot be read is skipped silently and `lh doctor`'s
**Transcripts** section carries the verdict, rather than the profile being
walked, found empty, and reported as having done no work — but it is now a
capability test. An agent that can be read is metered whatever it is called.

Because ingest now does read them, `lh doctor`'s `OK` line says `{agent} reads
{path}` again. It was softened to "has a reader for" precisely because ADR-051
made the pipeline decline what the reader offered, and a verdict that
contradicts the pipeline it exists to diagnose is worse than a blunt one.

**A second, optional Protocol answers session identity.** This is the part
ADR-051 did not anticipate, and it is required by the change it did propose:

```python
@dataclass(frozen=True)
class SessionIdentity:
    session_id: str
    project: str | None = None

@runtime_checkable
class TranscriptIdentity(Protocol):
    def session_identity(self, path: Path) -> SessionIdentity: ...
```

A row is keyed `(session, model)` and reported under a project, and **neither
is answerable from a transcript's contents**. Claude Code encodes both in the
path, including the `<parent>/subagents/` nesting that folds a subagent's turns
into the session that spawned it. Codex names the session in its file name —
the trailing uuid v7 equalled `session_meta.id` in 15/15 rollouts — and the
project only in `session_meta.cwd`, a record no signal is defined over. Left in
ingest, those two rules are exactly the per-dialect knowledge this ADR deletes
everywhere else.

It is **separate from `TranscriptReader` on purpose**, the idiom `HeadlessAgent`
and `SessionPinningAgent` already set in `base.py`. `isinstance` against
`TranscriptReader` is what `transcript_health` and `stop_verify_guard` gate on,
so folding the method in would make every reader that cannot identify a session
— including every test fake — report `DEGRADED` for a capability neither of
those callers needs. A reader that does not implement it degrades to the file's
own stem and no project, which is what every consumer did before.

`repo_name` moves from `monitoring/collector.py` to `core/project_identity.py`,
which already owned the `main_repo_root` rule it wraps. Metering now reaches it
from a Claude Code project directory *and* from a Codex `cwd`, and `agents/`
cannot import `monitoring/` without closing an import cycle.

**The hand parser stays.** ADR-051 kept it because ingest needed it; it stays
now for a different reason, which is that ingest is not its only consumer —
`lh exec` prices a session through `collector.session_cost_from_disk`, and
`parse_session` has its own callers. Two paths over one question is the repo's
gate, not its prohibition, and the gate's remedy is an integration test that
invokes both: `test_ingest_through_the_reader_bills_what_the_hand_parser_counted`
runs the pipeline and the hand parser over one corpus and compares the **stored
row**, which is where a disagreement would cost money.

**The `memory/` exclusion stays with the consumer.** It is the one dimension of
ADR-051's measured gap this ADR deliberately leaves open, for the reason
ADR-051 gave: what lives under `memory/` is a statement about what *this
harness* writes under an agent's config directory, not about the agent. A
reader taught to hide those files would be answering a question that is not its
own, and would hide them from every other consumer too. Both halves are
asserted — the reader yields them, ingest drops them.

## Alternatives rejected

**Folding `session_identity` into `TranscriptReader`.** One Protocol is tidier
and the blast radius is wrong: `runtime_checkable` `isinstance` checks method
presence, so every existing fake and any future read-only adapter would fail a
check two unrelated callers make, and `lh doctor` would report `DEGRADED` on
profiles whose transcripts are read perfectly well.

**Branching in ingest on the agent's name.** Deriving Claude's session from the
path and Codex's from `session_meta` inside `ingest_profile` would work, and
would reintroduce `_PARSED_DIALECT` under another name — one module knowing two
dialects, which is the coupling this ADR exists to delete.

**Deleting the hand parser.** Tempting once ingest stopped calling it, and
wrong: `lh exec` still prices sessions through it, so deleting it would have
moved the work rather than removed it.

**Leaving Codex rows without a project.** The cheapest option that still meets
the success criterion, and it ships a permanently degraded dimension for every
Codex row — the same fail-open shape as reporting an unreadable profile empty.

**A pseudo-model for Codex**, reconsidered and rejected again on ADR-051's
reasoning: `is_pseudo_model` exists for `<synthetic>` because those messages
consumed no tokens, and a Codex row would consume millions and report $0.

## Consequences

`lh metrics ingest` writes `session_stats` rows for a Codex profile: session and
project from the adapter, model from `turn_context`, tokens from
`token_usage_record`, `agent="codex"` and the profile's billing model from
ADR-050. A `flat_rate` profile prices to `cost=0.0, cost_source="subscription"`
and never fires `unknown_models`.

`TranscriptEvent` is wider by two fields and `TokenUsage` by one, on every
event every reader yields. Nothing is required to fill them.

The parity test changes shape rather than disappearing. What were three
asserted inequalities are now equalities over the same synthetic corpus, and
the `memory/` difference is still asserted from both ends. A future reader that
stops naming the model fails a test that names this ADR.

Codex's reader now depends on line order within a file. A rollout whose
`turn_context` is missing — truncated, rotated, or written by a release that
moves the field — meters its tokens under no model rather than the wrong one;
measured at 0 occurrences in 15 rollouts, and `None` is the answer either way.

`specs/designs/codex-evidence.md` §5.2 and §5.3 now record `turn_context` as
read, for one field, marked `[log], 0.154.0`.
