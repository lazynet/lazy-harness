# ADR-038: The `lh exec` envelope — cost provenance and the mute failure

**Status:** proposed
**Date:** 2026-08-31
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-037 (metric event schema v2), ADR-032 (agent adapter completeness), ADR-012 (SQLite monitoring)

## Context

ADR-037 gave metric events a `workload` dimension and, to carry it across a
kill, had `lh exec` pin the session id before spawning the agent. In doing so it
recorded two accounting holes in the `lh exec` envelope and left both open:

1. **`cost_usd: null` on every timeout.** `_base_envelope()` hardcodes it, and
   the timeout path emits that envelope unchanged. A kill is the most expensive
   outcome this command has and the only one with no return value, so the run
   the consumer most needs priced is the one it reports as free — while the
   ingest bills it. Reconciling the two means leaving the envelope and joining
   against the metrics store: two sources, keyed differently, for one event.

2. **A failed run reaching the consumer with no `error.kind`.** A well-formed
   envelope can carry `success: false` with `error: null` and an exit code
   matching none of the ones a consumer branches on. It parses cleanly and
   raises nothing: the failure arrives mute.

Neither is a defect in ADR-037 — both are consequences of it that its scope did
not cover. They are closed here.

This ADR is the **contract**. The harness side and the `lazy-ai-tools` side
(`lazy_shared_llm.headless`) are each built against this document, not against
the other's implementation.

## Decision

### The schema string does not move

The envelope stays `lh.exec/v1`. `lazy_shared_llm.headless._from_envelope`
opens with `if schema != SCHEMA: raise HeadlessProtocolError`, an exact
equality, so bumping the string breaks every consumer outright while appending
a key is ignored by every consumer that does not read it.

This is the opposite of ADR-037's D1, where `MetricEvent` *did* go to version 2 for two
appended fields. The difference is the reader, not the convention:
`MetricEvent.from_dict` tolerates absence with defaults; this one compares a
literal. **Compatibility is decided by the reader.**

### C1 — `cost_usd` is filled in place on the timeout path

The number is not moved to a new key. A new key would relocate the bug into
every consumer that sums `cost_usd` today, and each would keep under-counting
until individually updated — with the most expensive runs the ones still
reporting nothing.

The recomputed figure is not an estimate. It is the same measurement through
another door: the same session JSONL, deduplicated by `message.id` the same
way, priced with the same table, as the ingest bills from.

Populated from the transcript on a timeout:

| Field | Source |
|---|---|
| `cost_usd` | `calculate_cost` per model, summed |
| `prompt_tokens` | `input + cache_read + cache_create + cache_create_1h` |
| `output_tokens` | `output` |
| `cache_creation_tokens` | `cache_create + cache_create_1h` |
| `cache_read_tokens` | `cache_read` |

`prompt_tokens` is the **sum**, not `input_tokens` alone, and
`cache_creation_tokens` folds both cache-write buckets into one. Both match how
the success path already derives them in `parse_headless_result`, so a consumer
summing a field across runs is never mixing two definitions of it.

Left `null` on the timeout path: `num_turns` (the agent counts loop turns; a
transcript yields assistant messages — a different unit, and a wrong number is
worse than none), `duration_ms`, and `output`, which stays `""`.

### C2 — `cost_source` names the door

New key, `string | null`:

| Value | Meaning |
|---|---|
| `"agent"` | Claude Code's own `total_cost_usd`, passed through verbatim |
| `"transcript"` | Recomputed from the run's session JSONL with the harness pricing table |
| `null` | No cost figure at all |

**Invariant, and the only rule a consumer needs: `cost_source` is non-null if
and only if `cost_usd` is non-null.**

`null` covers: `--dry-run`; every harness error (`config`, `spawn-failed`,
`empty-prompt`, and the `LaunchError` kinds); a successful run whose agent
envelope carried no cost figure; a timeout whose transcript is missing, unreadable,
or holds no usage lines; and a timeout under an adapter that does not implement
`SessionPinningAgent`, which leaves no pinned stem to look up — degraded, not
broken.

The field exists because the two doors disagree by design. `parse_headless_result`
passes the agent's figure through verbatim and never recomputes it, precisely so
that a divergence from the harness table stays visible as a signal that the table
has gone stale — as of 2026-08-31 Claude Code bills `claude-sonnet-5` at
`claude-sonnet-4-6`'s rates, over-reporting those sessions by 50%. Filling
`cost_usd` from the harness table on one path and from the agent on the other,
with nothing to tell them apart, would have destroyed that signal. `cost_source`
preserves it at the cost of one key.

### C3 — a zero is never fabricated

`calculate_cost` returns `0.0` for a model absent from the pricing table, and a
sum over no usage lines is also `0.0`. Neither may reach the envelope: a `0`
enters a cost report as a fact, which is the same discipline that keeps
`cache_*` at `None` rather than `0` on the `lazy-ai-tools` side.

Therefore, on the transcript path:

- No assistant message with a usage block → `cost_usd: null`, `cost_source: null`,
  and the token counters stay `null` too.
- Usage lines present, but **any** model among them is absent from the pricing
  table and is not a pseudo-model (`is_pseudo_model`) → the token counters are
  filled and `cost_usd`/`cost_source` stay `null`. Tokens were counted; the run
  was not priced. A partial sum over the priced subset would be a real number
  for a fictitious run.

### C4 — a failed run always carries a kind

The condition is `result.success is False and the envelope carries no error
yet`. It is never "no error was set" alone: the timeout path sets its own kind
before this runs, and a harness failure never reaches here at all.

Two kinds, split on the evidence, because what a consumer does next differs.

**`no-envelope`** — the agent was spawned, exited non-zero, and its stdout held
no parseable JSON object (`result.raw is None`).

```json
{"kind": "no-envelope",
 "message": "agent exited 1 with no envelope on stdout; the cause, if any, went to its stderr, which lh exec does not capture"}
```

Named for the evidence rather than the symptom. The existing vocabulary —
`config`, `spawn-failed`, `empty-prompt`, `timeout` — names *what happened*;
`agent-failed` would have been a restatement of `success: false` and would tell
a reader of the log nothing new. `no-envelope` names what was actually observed
and points at the stderr, which is where the cause went and where whoever is
diagnosing has to look next.

**`agent-error`** — the agent returned a well-formed envelope and declared
itself failed in it: `is_error: true`, a non-zero exit, or both.
`parse_headless_result` derives `success` from
`exit_code == 0 and is_error is not True`, so this shape has a populated `raw`
and is exactly the half `no-envelope`'s guard excludes.

```json
{"kind": "agent-error",
 "message": "agent exited 1 reporting its own failure; its message is in `output`"}
```

The two are not one kind because the cause lives somewhere different in each.
For `no-envelope` it went to a stream this command does not capture and the
consumer must have kept; for `agent-error` it is in `output`, already in the
envelope the consumer is holding. Collapsing them would send a reader looking
for a stderr tail that never existed.

The message points at `output` and never replaces it. `output` is
`data["result"]` on this path — the agent's own account of what went wrong — and
overwriting it with a harness sentence would destroy the only description of the
cause that exists.

**Not covered, stated so it is not mistaken for covered:** an agent that exits
**0** with unparseable stdout still yields `success: true`, `error: null`.
`parse_headless_result` derives success from the exit code when it cannot parse,
and an `error` block on a successful envelope would contradict itself. That shape
is pre-existing and unchanged.

**Also unchanged:** `lh exec` keeps `stderr=None`, so the agent's stderr goes to
the caller's stderr and never reaches `error.message`. Capturing it would require
teeing to preserve the interactive pass-through; that is a larger decision and is
deliberately not taken here. The kind converts a mute failure into a typed one,
which is what the consumer needs in order to branch.

The message says "which `lh exec` does not capture" rather than "passed through
untouched", because *where* it goes is the caller's business and only the caller
knows. Interactively it reaches a terminal. `lazy-ai-tools` spawns with
`stderr=PIPE`, or redirects to a launchd log the next run overwrites — so
"passed through" would have described a destination that does not durably exist.

**Durability of the cause is the consumer's responsibility.** A consumer that
captures stderr may **append** its tail to `error.message` when
`kind == "no-envelope"`. The producer's message is a prefix and is never
machine-parsed by this repo — nothing here reads `error.message` back. The
appending consumer must not overwrite `kind`, must not rewrite the prefix, and
must not append on any other kind: on `timeout` the cause is the timeout itself,
and on the harness kinds the message is already the whole explanation.

Recorded because it was found the hard way: before `lh exec` stamped a kind, the
`lazy-ai-tools` side synthesised `error_message` from captured stderr *precisely
when the kind was null*. Stamping the kind here silently retires that synthesis
and would have destroyed the only durable copy of the cause — a producer fix
taking away a consumer's fallback path is not visible from either side alone.

### C5 — no exit code moves

| Path | Exit code | Before | After |
|---|---|---|---|
| Timeout | `EXIT_TIMEOUT` = 124 | 124 | 124 |
| No envelope | the agent's own return code | 1 | 1 |
| Harness error | `EXIT_HARNESS_ERROR` = 70 | 70 | 70 |
| Success | the agent's own return code | unchanged | unchanged |

Neither the new key nor the new kind moves an exit code. A consumer branching on
`returncode` — `EXIT_USAGE`, `EXIT_TIMEOUT` — keeps working byte for byte, and
`headless.py`'s `result.error_kind == "timeout" or returncode == EXIT_TIMEOUT`
needs no change.

### C6 — the recompute is fail-soft

Reading and pricing the transcript never changes `success`, `exit_code` or
`output`, and never raises out of `exec_cmd`. Any failure leaves `cost_usd` and
`cost_source` at `null`, which is exactly today's behaviour. Accounting about a
run must never be the reason the run reports differently — the same discipline
ADR-037's `_record_attribution` is already held to.

### C6b — every envelope has the same shape, on every path

`lh exec` has exactly four `_emit` call sites — `_fail`, `--dry-run`, timeout,
and the parsed result — and each builds its envelope from the one
`_base_envelope()` dict, overwriting values and never adding or removing a key.
`click.echo` in `_emit` is the only writer of stdout in the command.

So the timeout envelope carries the **identical key set** to the successful one,
`cost_source` included; a consumer needs no separate code path to read it. That
property is what makes the recompute in C1 reach the consumer at all, and it is
asserted rather than assumed.

**The shape is identical; the values are not.** On the timeout path `num_turns`
and `duration_ms` stay `null` even when `cost_usd` carries a figure. The only
implication a consumer may draw between fields is the C2 iff — `cost_usd`
non-null ⟺ `cost_source` non-null. Deriving "`cost_usd` is set, therefore
`num_turns` is set" breaks on exactly the run this ADR exists to account
for.

### C7 — what an older `lh` emits, and why the consumer's fallback is permanent

Every `lh` already installed keeps emitting the old shape, so the consumer side
is not relieved of any defence by this ADR:

- **No `cost_source` key at all.** A missing key is read as `null`, never as
  `"agent"`. Gate on the presence of the key, not on an `lh` version.
- **No `error.kind` on the no-envelope shape** — `success=False` with
  `error_kind is None`. That must remain its own error class in the consumer
  **indefinitely**. The producer fix reduces how often it fires; it does not
  retire it, and a consumer that drops the fallback breaks against any older
  harness on the most confusing failure it has.
- **`cost_usd: null` on every timeout**, with the ingest still the only
  subsystem that accounts for that run.

## Verification

- A timed-out run reports a `cost_usd` equal to what `ingest_profile` bills for
  the same transcript tree, asserted by invoking both over one fixture — the two
  code paths answering "what did this session cost" agree, and the deciding rules
  live in one importable place.
- That agreement holds for a session with subagent turns. `_find_session_files`
  folds `<session_id>/subagents/*.jsonl` into the parent's total, so a lookup
  reading only `<session_id>.jsonl` under-reports against the ingest on exactly
  the expensive runs.
- A timeout with no transcript, an unreadable transcript, and a transcript with
  no usage lines each leave `cost_usd` and `cost_source` at `null` — and the exit
  code at 124 in all three.
- A transcript naming a model absent from the pricing table fills the token
  counters and leaves `cost_usd` null, rather than reporting `0.0`.
- A failed run with empty stdout carries `error.kind == "no-envelope"`; one that
  returned a well-formed envelope declaring `is_error` carries
  `error.kind == "agent-error"` with the agent's own message still in `output`;
  one with exit 0 and unparseable stdout carries `error is None` and
  `success is true`.
- `cost_source` is `"agent"` on a successful run and `null` on one whose agent
  envelope carried no cost figure, pinning the iff invariant from both sides.
- The timeout envelope and the successful envelope have equal key sets, asserted
  by comparing them directly rather than by listing the keys a test expects.
