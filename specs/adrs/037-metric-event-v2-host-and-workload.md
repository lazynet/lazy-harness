# ADR-037: Metric event schema v2 — `host` and `workload` as first-class dimensions

**Status:** proposed
**Date:** 2026-08-31
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-012 (SQLite monitoring), ADR-032 (agent adapter completeness), ADR-035 (capability registry)

## Context

`MetricEvent` (`plugins/contracts.py`) is the wire format every metrics sink
consumes. At schema version 1 it carries eleven dimensions and measures:
`event_id`, `schema_version`, `user_id`, `tenant_id`, `profile`, `session`,
`model`, `project`, `date`, the four token counters, and `cost`.

Two questions the current dimensions cannot answer.

### 1. Which machine spent this?

`resolve_identity` (`core/identity.py:65`) resolves `user_id` through
`explicit → gh → git → implicit`, and only the **implicit** branch stamps a
host, as `f"{user}@{host}"`. Every other branch drops the machine entirely.

On this machine the resolution never even reaches `gh`: `~/.config/lazy-harness/config.toml`
pins `[metrics] user_id = "lazynet"`, so it stops at the **explicit** branch.
That makes the collapse stronger than a `gh` coincidence — it is configured.
`gh api user --jq .login` returning the same login on both machines, and the
`gh` install now in progress on the `agents` CT, only remove the fallbacks that
might otherwise have differed. No path through this function can stamp a host
while `user_id` is pinned.

There is no dimension that survives this.
`profile` is a harness concept, `project` is a
repository, and neither is a machine.

### 2. Which pass spent this?

Nothing in the event identifies the *caller* of a headless run. A batch job
that invokes the agent repeatedly is indistinguishable, in the metrics, from
interactive work in the same repository under the same profile.

### The open question this ADR had to answer first

The ingest derives everything from the agent's own session transcripts:
`monitoring/ingest.py` walks `<config_dir>/projects/`, `collector.py` parses
each JSONL, `extract_project_name` derives `project` from the encoded cwd, and
`profile` comes from which profile's `config_dir` the tree sits under. A value
passed on an `lh exec` command line does not obviously reach any of that.

So before designing a breaking schema change, the question was: **does a
channel exist from an `lh exec` invocation to the ingest, and if not, what is
the cheapest one to build?**

## Spike

### Finding 1 — no field in the transcript carries a caller-supplied value

The union of top-level keys across 931 JSONL lines from five recent sessions:

```
type sessionId timestamp parentUuid isSidechain uuid userType entrypoint cwd
version gitBranch session_id message requestId effort attachment promptId
toolUseResult sourceToolAssistantUUID attributionSkill attributionPlugin
permissionMode leafUuid atis bridgeSessionId lastSequenceNum ownerAccountUuid
ownerOrganizationUuid mode lastPrompt aiTitle messageId snapshot ...
```

The only environment-derived fields are `cwd`, `gitBranch`, `version`,
`userType` and `entrypoint`. None is caller-supplied and none is free-form.
`entrypoint` does separate headless (`sdk-cli`, 31 of 40 recent sessions) from
interactive (`cli`, 9), which confirms `lh exec` runs *are* already ingested —
but it is a fixed enum, not an attribution label.

**A value handed to `lh exec` does not reach the transcript. The channel does
not exist today.**

### Finding 2 — `session` is the only join key the ingest already owns

Every ingested row is keyed by `(session, model)`, where `session` is the
transcript's filename stem. Anything that can be keyed by session id can be
joined onto the event at ingest time.

### Finding 3 — `lh exec` can *choose* the session id, before spawning

Claude Code 2.1.251 exposes `--session-id <uuid>`, and honours it. Verified by
running one real headless call with a generated UUID:

```
$ UUID=925529e2-211b-4f64-b2a2-90a4f57b23c9
$ echo "say OK" | claude -p --output-format json --model haiku --session-id $UUID ...
```

- the stdout envelope echoed `"session_id": "925529e2-…"` — the exact UUID
  supplied, and a field `lh exec` does not read today;
- the transcript was written to
  `…/projects/-private-tmp-…-scratchpad/925529e2-….jsonl`, whose stem is that
  UUID and whose `sessionId` field matches.

So `lh exec` can decide the ingest's join key *before* any token is spent.

**The channel does not exist, but it is one flag and one table away, and its
key is the one the ingest is already built on.**

### Finding 4 — a session id already in use is refused, not resumed

Measured, because "the agent silently continues someone else's conversation"
would have been a correctness bug and not merely an accounting one. The same
UUID was passed a second time, from the same cwd, with a different prompt:

```
$ echo "What exactly did I ask you in my previous message?" \
    | claude -p --output-format json --model haiku --session-id 925529e2-… …
EXIT=1
stderr: Error: Session ID 925529e2-211b-4f64-b2a2-90a4f57b23c9 is already in use.
stdout: (empty)
```

The existing transcript was left byte-identical — 18 lines, 50898 bytes,
unchanged mtime. So Claude Code refuses up front: **no implicit resume, no
fork, no silent append**. Two different `workload` labels can never end up
sharing one transcript through session-id reuse, which is what makes the
pre-spawn write in D4 safe.

The cost of the refusal is a specific shape of failure. `lh exec` would receive
`returncode=1` and an **empty stdout**, so `parse_headless_result`
(`agents/claude_code.py:176`) degrades to `success=False, output="", raw=None`
and the emitted envelope carries no `error.kind` — the only explanation reaches
the user through the agent's stderr, which `lh exec` passes through untouched
(`cli/exec_cmd.py:201`, `stderr=None`).


### Finding 5 — attribution survives the timeout, because the ingest is the only thing that bills it

This is the property the whole pre-spawn ordering in D4 rests on, so it was
measured rather than argued. Two real timed-out runs plus one emulation of
`lh exec`'s own timeout path with a session id pinned.

**Run 1 — `lh exec --timeout 5`, single turn, killed mid-generation.**
Exit 124 in 5.9s. A transcript *was* written (15 lines, 65654 bytes) but it
holds no assistant message at all:

```
tipos de linea: {'queue-operation': 2, 'attachment': 10, 'user': 1,
                 'last-prompt': 1, 'atis-latch': 1}
iter_assistant_messages(...) -> 0 mensajes con usage
```

`ingest_profile` skips it outright — `if not messages: continue`
(`monitoring/ingest.py:135`). No row, no event, no cost.

**Run 2 — `lh exec --timeout 25`, multi-turn with `--allow-tools Bash`, killed
after eight tool round-trips.** Exit 124 in 25.4s. Here the assistant turns
*were* flushed: 25 `assistant` lines, 9 unique `message.id` after the ingest's
own dedup, and the repo's own pricing puts the bill at

```
tokens (deduplicados): input 73  output 966  cache_read 259229  cache_create_1h 17850
COSTO que el ingest facturaria: $0.066526
```

while the envelope `lh exec` emitted for that same run reported
`"cost_usd": null`.

**Run 3 — the same shape with the session id pinned**, driven through
`lh exec`'s real `_terminate_group` / `_base_envelope` / `EXIT_TIMEOUT`
(`cli/exec_cmd.py`) rather than an approximation of them. Pinned
`c02bfa9d-ba8e-4f9d-91bd-96df64c7b8ce`; after the kill:

```
$ ls …/projects/-private-tmp-…-scratchpad/c02bfa9d-….jsonl
.rw------- 104k lazynet 31 Aug 11:19
sessionId adentro: c02bfa9d-ba8e-4f9d-91bd-96df64c7b8ce   entrypoint: sdk-cli
msg_ids unicos: 9  ->  COSTO: $0.059059
```

The transcript exists **at the pinned stem**, carries the pinned id internally,
and is billable. The kill does not prevent the pin from taking effect.

### The invariant this establishes

The two outcomes are complementary, and that is the whole point:

| kill lands | transcript | ingest bills | attribution row |
|---|---|---|---|
| before the first assistant turn is flushed | exists, no usage lines | **nothing** (`ingest.py:135`) | orphan, harmless |
| after any assistant turn is flushed | exists, usage lines present | **yes** | present, joins |

**There is no case in which cost is billed without attribution.** That is
exactly what the pre-spawn write buys, and it is now measured rather than
assumed. The post-hoc alternative would have lost the second row entirely —
the envelope carries `cost_usd: null` on a timeout, so `lh exec` itself never
learns what the run cost. The ingest is the *only* subsystem that accounts for
a timed-out run, which is why attribution has to be resolvable there.

Corollary worth recording separately: **`lh exec` under-reports cost on every
timeout.** `cost_usd`, all four token counters and `num_turns` come back `null`
while the ingest bills $0.066526 for the same run. That is a pre-existing
accounting gap, independent of this ADR. It is closed by the amendment at the
end of this document, not by the schema change itself.


## Decision

### D1 — schema version 2, two appended fields

```python
METRIC_EVENT_SCHEMA_VERSION: int = 2

host: str = ""
workload: str = ""
```

Appended last, both defaulted to the empty string, so `MetricEvent.from_dict`
accepts a v1 payload unchanged. `host` is its own dimension; it is **not**
folded into `user_id`. This follows the precedent set in `lazy-ai-tools`
commit `586bcfe`, which added `host` to `executions.jsonl` as a field of its
own rather than nesting it inside an existing identifier.

The field name `workload` is settled. It was chosen over `label` (which in
Grafana and Prometheus already *means* "dimension", so the panel vocabulary
would collide), and over `run_label`, `caller` and `tag`. The harness never
interprets the string — it has no knowledge of any specific caller.

### D2 — `user_id` keeps its meaning

`resolve_identity` is not touched. `user_id` identifies the person; the
implicit branch keeps emitting `user@host` even though `host` is now its own
column. Changing it would rewrite the identity of every row already in
Postgres and break the continuity of the existing history for no gain.

### D3 — `host` is resolved at ingest, not carried through a channel

The process that ingests a profile's transcripts is running on the machine
that produced them, so `host` needs no channel at all — `ingest_all` resolves
it once and stamps every event.

The normalisation must be the *same* one `resolve_identity` already applies —
leading DNS label only, so `LazyMBP.local` and a DHCP-renamed `LazyMBP-2.local`
do not split one machine in two. That rule therefore moves into a single
exported `resolve_host()` in `core/identity.py`, and the implicit branch of
`resolve_identity` calls it instead of repeating it. Two code paths answering
"what host is this" must answer from one place.

Assumption made explicit: a `config_dir` is local to the machine that writes
it. If a profile's `projects/` tree were ever synced between machines, the
ingesting host would mislabel the other machine's sessions. That is not the
case in this fleet and is not defended against.

### D4 — `workload` is caller-supplied, and travels on a pre-assigned session id

New option on `lh exec`:

```
--workload TEXT      Free-form attribution label for this run (default: "")
```

also readable from `LH_WORKLOAD` in the environment, so the
`[llm].binary = "lh exec --profile lazy"` contract can express it either as
`lh exec --profile lazy --workload <label>` or by exporting the variable.
The harness never interprets the string; it has no knowledge of any specific
caller.

Mechanism, in order:

1. `lh exec` generates a UUID4.
2. It writes `session_attribution(session, workload, host, created_ts)` into
   the metrics DB — **before** spawning, so an attribution row exists before
   any token is billed.
3. It passes the UUID to the agent as its session id.
4. The agent writes its transcript under that stem.
5. `ingest_profile` looks the session up in `session_attribution` and stamps
   `workload` on the event. A session with no row gets `""`.

Two properties this ordering buys, both of which the post-hoc alternative
loses: a run killed by the 600s timeout — the single most expensive outcome
`lh exec` has — is still attributed, and so is one whose stdout envelope is
unparseable.

Belt and braces: after a successful parse, `lh exec` compares the agent's
reported `session_id` against the UUID it assigned and rewrites the row under
the reported id if they differ. An exit code is not proof that a flag took
effect.

Every write on this path is fail-soft. `lh exec` must not fail a run because
attribution could not be recorded; the same discipline hooks are held to.

**The UUID is generated fresh on every invocation and never persisted,
reused, or retried with.** Finding 4 makes reuse a hard failure rather than a
silent one, which is the safe direction, but it means a wrapper that retries
`lh exec` with a remembered id gets exit 1 and an empty envelope. Collision
between two independent UUID4s is not the risk; reuse by a caller is.

A run that dies before writing a transcript — refused session id, spawn
failure, a kill before the first token — leaves an orphan row in
`session_attribution` that no session will ever join. Orphans are harmless to
every reader (the join simply misses) and are not pruned by this ADR, but the
table grows monotonically with failed runs and that is a known, accepted cost.

### D5 — the adapter seam for the session id

`headless_argv`'s signature is part of the `HeadlessAgent` Protocol, so
widening it in place breaks any third-party adapter. Instead, per ADR-032,
a new optional Protocol method:

```python
def session_argv(self, session_id: str) -> list[str]: ...
```

Claude Code returns `["--session-id", session_id]`. An adapter that cannot
pin a session id returns `[]`, and `lh exec` then falls back to reading the
session id out of the parsed result — degraded, not broken.

`HeadlessResult` also gains `session_id: str | None = None`, populated by
`parse_headless_result` from the envelope.

**Implemented as a separate `SessionPinningAgent` Protocol**, not as a method on
`HeadlessAgent`. `HeadlessAgent` is `@runtime_checkable` and `lh exec` gates on
`isinstance`, so a method declared there would have made every adapter without
it fail that check and be refused outright — the opposite of optional. A second
capability Protocol is the same idiom `HeadlessAgent` already applies to
`AgentAdapter`, one level down, and `tests/unit/test_agent_headless.py` pins an
adapter that satisfies `HeadlessAgent` while failing `SessionPinningAgent`.

### D6 — `event_id` inputs are unchanged

`derive_event_id(profile, session, model)` stays as it is. Adding `host` or
`workload` would mint new ids for events already sent, and the remote upserts
by `event_id` — every historical event would re-land as a new row and double
the recorded cost. Session ids are UUIDs, so the collision `host` would guard
against does not occur in practice.

`workload` is a mutable attribute of an event, not part of its identity: a
mislabelled run can be corrected without minting a new event.

### D7 — interactive sessions are out of scope

`lh exec` is the only writer of `session_attribution` in this ADR. Interactive
sessions carry `workload = ""`, and that is correct rather than missing — no
caller asked for them.

The table is the extension point. A `session_start` hook reading `LH_WORKLOAD`
from its inherited environment and writing the same row would extend
attribution to interactive sessions without touching the schema or the ingest.
That is deliberately not built here.

## Alternatives considered

| Option | Why not |
|---|---|
| Resolve `workload` at ingest from what is already in the transcript | Nothing caller-supplied is in there (Finding 1). `entrypoint` is a fixed enum and `cwd` is already `project`. |
| Write the attribution row *after* the run, from `raw["session_id"]` | Smaller — no Protocol method — but loses attribution exactly on timeouts and unparseable envelopes, which are the expensive runs. Kept as the degraded fallback in D5. |
| Append-only `attribution.jsonl` sidecar instead of a table | Grows unbounded, needs its own pruning, and re-parses in full on every ingest. The DB already has WAL, a busy timeout, and gives idempotency from a primary key. |
| Fold `host` into `user_id` | Changes the meaning of an existing dimension and rewrites the identity of every historical row. Explicitly rejected; see D2. |
| Encode the label into `tenant_id` | `tenant_id` names an organisation, not a run. Overloading it makes both dimensions unqueryable. |
| One dedicated profile per caller | Abuses `profile`, which selects a config dir and a credential; it would fork the agent's whole state per label. |

## Consequences

### Inside this repo

- `plugins/contracts.py` — version 2, two fields. The module's own docstring
  requires coordinating every registered sink; both built-ins are covered
  below.
- `monitoring/db.py` — `session_stats` gains `host` and `workload` via the
  existing `PRAGMA table_info` + `ALTER TABLE` pattern (`_migrate_identity_columns`);
  a new `session_attribution` table; `upsert_event` writes the new columns;
  `query_stats` projects a fixed dict and must be extended or `lh status`
  cannot group by either.
- **Two writers, one row.** `ingest_profile` calls `upsert_stats` (no identity
  columns) and *then* the `sqlite_local` sink calls `upsert_event` (identity
  columns). With `sqlite_local` disabled, `host` and `workload` stay empty in
  the local DB while the remote sink receives them. Pre-existing shape, now
  affecting two more columns; an integration test must pin it.
- `monitoring/ingest.py` — resolve host once, join attribution per session.
- `monitoring/aggregate.py` — `DIMENSIONS` and `FILTERABLE` gain both;
  `_dimension_value` handles them.
- `cli/status_cmd.py` — `--group-by` is `click.Choice(DIMENSIONS)`, so it picks
  the new dimensions up for free once `query_stats` returns them.
- `cli/exec_cmd.py` — the `--workload` option, the UUID, the fail-soft write,
  the reconciliation.
- `agents/base.py`, `agents/claude_code.py` — `session_argv`,
  `HeadlessResult.session_id`.
- `core/identity.py` — `resolve_host()` extracted and reused.
- Sinks: `http_remote` serialises `event.to_dict()` and needs no change;
  `sqlite_local` needs the columns. `lh metrics status` reads the outbox and
  is unaffected.

### Outside this repo — sequenced separately, not by this change

- The Postgres `events` table needs `host TEXT NOT NULL DEFAULT ''` and
  `workload TEXT NOT NULL DEFAULT ''`, and its receiver must accept payloads
  that omit both. Pending outbox rows hold v1 payloads and drain verbatim, so
  the receiver will see v1 and v2 concurrently for as long as the backlog
  lasts.
- The six `rawSql` panels in the Grafana dashboard select named columns and
  keep rendering unchanged. The panel labelled "Cost per account" groups by
  `profile`; `host` and `workload` are what would let it mean what it says.
- `lazy-vault` expresses the label through its `[llm].binary` string or
  `LH_WORKLOAD`. This ADR only declares that contract.

### Cross-repo consequence — a refused run reaches `lazy-ai-tools` without a cause

Recorded here so it is not rediscovered. **Not fixed by this ADR, and
`lazy-ai-tools` is not touched by it.**

Finding 4 showed the agent refusing a reused session id with exit 1 and an
**empty stdout**. Traced through both sides:

Harness side — `parse_headless_result("", 1)`
(`src/lazy_harness/agents/claude_code.py:176`) degrades to
`HeadlessResult(success=False, output='', exit_code=1, raw=None)`, and
`exec_cmd` emits a *well-formed* envelope from it
(`src/lazy_harness/cli/exec_cmd.py:224-243`):

```json
{"schema": "lh.exec/v1", "success": false, "exit_code": 1,
 "output": "", "cost_usd": null, "error": null, "raw": null}
```

Consumer side — `lazy-ai-tools`, `shared/lazy-shared-llm/src/lazy_shared_llm/headless.py`:

- `:252` `json.loads(stdout_text)` **succeeds** — the envelope is valid JSON, so
  the `HeadlessProtocolError` at `:257` never fires. This is worth stating
  plainly because it is the opposite of the intuition: the failure does not
  arrive as a protocol error.
- `:129` `error = data.get("error") or {}`, so `:144-145` set
  `error_kind=None` and `error_message=None`.
- `:246` `returncode == EXIT_USAGE` is false (`EXIT_USAGE = 2`, `:43`).
- `:263` `error_kind == "timeout" or returncode == EXIT_TIMEOUT` is false
  (`EXIT_TIMEOUT = 124`, `:45`).

No branch matches, so `run()` **returns normally** with
`AgentResult(success=False, output="", error_kind=None, error_message=None)`.
The only explanation — `Error: Session ID … is already in use.` — travelled on
the agent's stderr, which `lh exec` passes through untouched
(`cli/exec_cmd.py:201`, `stderr=None`) and which `headless.py:225` sends to
`stderr_sink or subprocess.PIPE`; when no `log_file` was passed, `:230`
discards the stderr half of `communicate()` into `_`. The cause is destroyed.

The timeout path, by contrast, is handled correctly on both sides: `lh exec`
sets `error.kind = "timeout"` with exit 124 and `headless.py:263-265` raises
`HeadlessTimeoutError` carrying the message. It is specifically the
*agent-failed-with-empty-stdout* shape that arrives mute.

Whoever picks this up owns the choice of which side fixes it — `lh exec`
stamping an `error.kind` when the agent fails with nothing on stdout, or the
consumer treating `success=False` with a null `error_kind` as its own error
class. Both are defensible; neither is decided here. **Resolved 2026-08-31 —
see the amendment at the end of this document: `lh exec` stamps
`error.kind: "no-envelope"`, and the consumer keeps its null-kind fallback
permanently, for older harnesses.**

## Deploy order

The order is **not yet decided**, because it hangs on one unmeasured property of
the Postgres receiver. This section states the condition and both branches so
that whoever has the measurement can pick a branch without reopening the
decision.

### The deciding question

**Does the receiver accept a POST body that omits `host` and `workload`?**

It has to be asked in that direction, not as "does it accept v2". Pending rows
in `sink_outbox` hold **v1** payloads and drain verbatim — `drain_http_remote`
posts `row.payload_json` without deserialising it
(`monitoring/sinks/worker.py`), so the receiver will be fed v1 and v2
concurrently for as long as the backlog lasts, whatever order we deploy in.
A receiver that rejects unknown *or* missing keys breaks one of the two.

**Resolved 2026-08-31: Branch B.** The receiver was made tolerant in both
directions and deployed first — 18 columns, 3393 pre-existing rows intact, zero
`db_error`, 11 real v1 events accepted during the window, and the rollback
measured non-destructive because the previous UPSERT does not name the new
columns and so cannot overwrite `host`/`workload`. `lazy-ansible` commit
`c40248f`. The harness side is what remains.

The original framing is kept below because it is what the branch was chosen
against.

Measurement in progress against `lazy-ansible`, separately from this repo. The
receiver lives at `lazy-ansible/docker/lh-metrics/app.py` — which matters for
the choice below: it is a component we own, so Branch A can be *made* true
rather than merely hoped for. Making the receiver tolerant in both directions
first collapses the decision to Branch A permanently, and is cheaper than
sequencing Branch B on every future schema bump.

### Branch A — receiver tolerant of missing/unknown fields

*Condition: a body without `host`/`workload` is accepted, and a body carrying
them is accepted and ignored (or stored).*

1. Harness ships first: merge, let release-please cut, `uv tool install --reinstall`,
   grep site-packages to confirm the code shipped.
2. `lh` starts emitting v2. The receiver ignores the two new keys; nothing
   observable changes.
3. Postgres columns and receiver mapping land whenever convenient.
4. The dashboard gains the two dimensions last.

Backlog is a non-issue: both versions are acceptable at every step, so there
is no window in which drainage can fail.

### Branch B — receiver strict about its payload shape

*Condition: the receiver rejects a body with unknown keys, or requires every
column to be present.*

Order inverts, and the harness goes **last**:

1. Postgres first: `ALTER TABLE events ADD COLUMN host TEXT NOT NULL DEFAULT ''`
   and the same for `workload`. Defaults, not `NOT NULL` bare, so v1 inserts
   keep working.
2. Receiver next, made tolerant in **both** directions before anything else
   moves — it must accept a v1 body (missing both keys) and a v2 body
   (carrying both). Verify with a hand-crafted POST of each shape before
   proceeding; a gate is trusted only after being fed a case it must pass and
   a case it must fail.
3. Only then the harness: merge, release, reinstall, grep site-packages.
4. Dashboard last.

Between steps 1 and 2 the pending v1 backlog must keep draining. If the
receiver cannot be made tolerant in place, drain the outbox to zero *before*
step 2 and hold the harness at v1 until the receiver is replaced — the outbox
retries with backoff and loses nothing, but a partial migration with a strict
receiver will burn attempts against every pending row.

### Invariant common to both branches

`event_id` inputs do not change (D6), so an event already sent stays the same
event. Re-sending after the migration upserts onto the existing row instead of
duplicating it, in either order. That is what makes both branches reversible:
rolling the harness back to v1 leaves the two columns populated with `''` and
nothing else disturbed.

## Verification

- The channel: run `lh exec --workload X`, then assert the row in
  `session_attribution`, the transcript filename, and the `workload` on the
  ingested event all carry the same session id — the artifact is verified by
  the system that consumes it, not by the test that wrote it.
- The timeout path: an `lh exec` killed at its timeout still leaves an
  attributed row.
- v1 compatibility: `MetricEvent.from_dict` on a stored v1 payload, and a
  `session_stats` row written before the migration, both still render through
  `lh status` and `lh metrics status`.
- Host normalisation: `resolve_host` and the implicit branch of
  `resolve_identity` agree on `LazyMBP.local` and `LazyMBP-2.local`.
- The `sqlite_local`-disabled configuration: assert what the local columns
  hold, so the two-writer shape is pinned rather than discovered later.
- Session-id reuse: assert `lh exec` mints a fresh UUID per invocation and
  never reads one back from disk or from the environment. Finding 4 shows the
  agent refuses a reused id with exit 1 and an empty stdout, so a wrapper that
  retries with a remembered id would get an envelope with no `error.kind`.
- Orphan attribution rows: a run refused or killed before its first token
  leaves a `session_attribution` row no session joins; assert every reader
  tolerates it rather than counting it.

## Amendment 2026-08-31 — the `lh exec` envelope: cost provenance and the mute failure

This ADR recorded two accounting holes in the `lh exec` envelope and left both
open: `cost_usd: null` on every timeout (Finding 5, corollary) and a failed run
reaching the consumer with no `error.kind` (cross-repo consequence, above).
Both are closed here, and this section is the **contract** — the harness side
and the `lazy-ai-tools` side are built against it, not against each other's
implementation.

### The schema string does not move

The envelope stays `lh.exec/v1`. `lazy_shared_llm.headless._from_envelope`
opens with `if schema != SCHEMA: raise HeadlessProtocolError`, an exact
equality, so bumping the string breaks every consumer outright while appending
a key is ignored by every consumer that does not read it.

This is the opposite of D1, where `MetricEvent` *did* go to version 2 for two
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

### C4 — `error.kind: "no-envelope"`

Stamped when the agent was spawned, exited non-zero, and its stdout held no
parseable JSON object — `result.success is False and result.raw is None`.

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
`_record_attribution` is already held to.

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
`num_turns` is set" breaks on exactly the run this amendment exists to account
for.

### C7 — what an older `lh` emits, and why the consumer's fallback is permanent

Every `lh` already installed keeps emitting the old shape, so the consumer side
is not relieved of any defence by this amendment:

- **No `cost_source` key at all.** A missing key is read as `null`, never as
  `"agent"`. Gate on the presence of the key, not on an `lh` version.
- **No `error.kind` on the no-envelope shape** — `success=False` with
  `error_kind is None`. That must remain its own error class in the consumer
  **indefinitely**. The producer fix reduces how often it fires; it does not
  retire it, and a consumer that drops the fallback breaks against any older
  harness on the most confusing failure it has.
- **`cost_usd: null` on every timeout**, with the ingest still the only
  subsystem that accounts for that run.

### Verification this amendment adds

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
- A failed run with empty stdout carries `error.kind == "no-envelope"`; one with
  exit 0 and unparseable stdout carries `error is None` and `success is true`.
- `cost_source` is `"agent"` on a successful run and `null` on one whose agent
  envelope carried no cost figure, pinning the iff invariant from both sides.
- The timeout envelope and the successful envelope have equal key sets, asserted
  by comparing them directly rather than by listing the keys a test expects.
