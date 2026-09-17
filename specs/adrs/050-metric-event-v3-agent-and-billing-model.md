# ADR-050: `MetricEvent` v3 — `agent`, and a billing model that admits flat rates

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-037 (metric event v2 — host and workload, the schema-append mechanism this ADR reuses), ADR-045 (the credential boundary), ADR-004 (agent adapter pattern)

## Context

Blast-radius design decision 3
(`specs/designs/2026-09-13-multi-agent-blast-radius-design.md:454-516`) asks for
three changes in one schema bump: which agent produced a row, and whether that
row's cost is real per-token spend or an unmetered subscription.

Measured on `main` at `fbfb8e8` before this change: `METRIC_EVENT_SCHEMA_VERSION
= 2`; `MetricEvent` carries `host`/`workload` appended with defaults after v1
(ADR-037); `aggregate.py` `DIMENSIONS`/`_STRING_DIMENSIONS` have no `agent`;
`cost_source` exists only on the `lh exec` envelope (`cli/exec_cmd.py`), never
on a metric row; the only `MetricEvent(` construction is `ingest.py:206`.

### Why not per-agent billing

The previous revision of this decision put the billing model on the agent.
That is wrong on this machine's own evidence: `~/.codex/auth.json` carries
`auth_mode`, `OPENAI_API_KEY` and `tokens` at once. The same agent bills by
subscription under a ChatGPT sign-in, per token under an API key, and nothing
at all under `--oss` against a local model. Stamping `flat_rate` on `"codex"`
would report an API-key profile's real spend as zero — the failure this
decision exists to prevent, relocated one level up from the agent to the
profile that is not the agent either.

### Why not read `~/.codex/auth.json` (or any credential file)

The design says the billing model is "resolved per profile from its execution
context." Reading a credential file to infer it would satisfy that sentence
literally, but ADR-045 drew the line: the harness never reads a credential
file to infer anything — that file is a secret store, not a configuration
source, and a reader that opens it for one bit of information is a reader
that can be asked to open it for another. The billing model is a per-profile
**config field** instead: `[profiles.<name>] billing_model = "per_token" |
"flat_rate"`, default `per_token`. This is the reading of the design that
respects the boundary ADR-045 already drew, not a smaller version of reading
the credential file.

## Decision

### D1 — schema version 3, three appended fields

```python
METRIC_EVENT_SCHEMA_VERSION: int = 3

agent: str = ""
billing_model: str = "per_token"
cost_source: str | None = None
```

Appended after `workload`, all defaulted, following ADR-037's mechanism
exactly: a v1 or v2 payload — pending outbox rows, a stored event — has none
of the three and still loads through `from_dict` unchanged. `agent` and
`billing_model` are persisted rather than resolved at read time because the
execution context that decides them (which adapter, which auth mode) is
mutable and the row is permanent — the same argument ADR-037 made for `host`.

### D2 — `derive_event_id` is unchanged

`derive_event_id(profile, session, model)` stays exactly as it was. Two
events differing only in `agent` share an id — that is intended, not a bug:
adding `agent` to the id would mint new ids for events already sent, and the
remote upserts by `event_id`, so every historical event would re-land as a
new row and double the recorded cost. `agent` is a mutable attribute of an
event's identity in the same sense `workload` was under ADR-037 D6, not part
of what makes the row unique.

### D3 — `billing_model` is a validated per-profile config field

`ProfileEntry.billing_model: str = "per_token"`. The loader validates the
value against `BILLING_MODELS = ("per_token", "flat_rate")` and names the
misspelling in its diagnostic:

```
[profiles.beta].billing_model='flatrate' is not one of per_token, flat_rate
```

`docs/reference/config.md` documents the field under `[profiles.<name>]`,
where the coherence test compares the doc against `ProfileEntry`'s fields.

### D4 — cost and `cost_source`, decided by billing model

`pricing.cost_for_billing_model(model, tokens, pricing, billing_model=...,
on=...)` returns `(cost, cost_source)`:

- **`flat_rate`** short-circuits pricing entirely: `cost = 0.0`,
  `cost_source = "subscription"`, unconditionally — the per-token table is
  never consulted, so an unrated model does not turn into a false "unpriced"
  gap. This row never adds to `unknown_models`.
- **`per_token`** keeps `calculate_cost`'s existing behaviour. `cost_source =
  "pricing"` when the model has a rate (or is a pseudo-model), `None` when it
  does not — the one case `cost_source` exists to name: *pricing was
  attempted and failed*. A `None` `cost_source` is exactly the condition
  `ingest.py` uses to populate `unknown_models`, replacing the old
  `model not in pricing and not is_pseudo_model(model)` check with the
  billing-model-aware one.

`calculate_cost` itself is untouched — its signature and every existing
caller (`collector.py`, its own test suite) is unaffected. The billing-model
branch lives in a new function beside it in `pricing.py`, per the design's
"in `calculate_cost` or its caller."

### D5 — `agent` is resolved per profile at ingest, not carried through a channel

Like `host` (ADR-037 D3), the ingest already runs against a `Config` that
knows every profile's adapter. `ingest_all` resolves it with the existing
`agents.registry.agent_for_profile(cfg, profile_name).name` — the same
function `lh deploy` and `lh run` already use to avoid two readers of
"which agent does this profile run" drifting apart — and passes both `agent`
and `billing_model` down to `ingest_profile`, which stamps them onto every
row and event it builds. `ingest_profile`'s directory-resolution code
(`:109-135`) is untouched; only the row-building hunk and the
`unknown_models` branch change.

### D6 — `agent` is a dimension; `billing_model` decides what a bucket's cost means, not what it's grouped by

`aggregate.py` `DIMENSIONS`, `_STRING_DIMENSIONS` and `FILTERABLE` gain
`agent` — a fourth thing a row can be grouped or filtered by, alongside
`host` and `workload`. `billing_model` does **not** become a dimension: it is
not a fact a reader groups cost by, it is what tells a reader whether a
bucket's cost number means anything. `Bucket` gains `billing_models: set[str]`
and `all_flat_rate` (true exactly when every row seen is `flat_rate`), which
every view reads to decide how to render.

### D7 — rendering keeps the distinction; it is never thrown away

A `flat_rate` bucket keeps its sessions and tokens — the usage is real — but
its cost cell renders `—`, never `$0.00`. A total or `all:` rollup spanning
both billing models is relabelled *priced only* rather than silently summing
a subscription profile's real usage into a number that reads as "total
spend." In JSON (`tokens.py render_json`) the cost is `null` alongside
`cost_source: "subscription"`, so a machine consumer distinguishes the two
cases without parsing the render. Implemented in `overview.py` (the
Sessions/Tokens panel, per-profile and `all:`), `tokens.py` (`lh status
tokens`, per-group and `Total`), and `sessions.py` (`lh status sessions`,
per-day and `Total`) — every view `grep cost` found in
`monitoring/views/`.

Precedent: `monitoring/views/overview.py`'s cache line is kept off the
tokens row on purpose, because two numbers that do not belong in one
aggregate are not put in one aggregate. A flat-rate zero summed into a
per-token total and labelled as if it were the whole story is the same
conflation.

### D8 — no sink needed widening

`grep -rn "workload|host" src/lazy_harness/monitoring/sinks/` returns
nothing: `http_remote` serialises `event.to_dict()` generically and already
carries whatever fields the dataclass has (the ADR-037 precedent this ADR
relies on again); `worker.py` reposts `payload_json` verbatim and never
touches a field name; `sqlite_local` delegates the column list to
`db.upsert_event`, which Part 3's schema change already widened. Pinned with
a v3 event through all three, including the outbox's real POST body.

`db.py`'s `session_stats` table gains `agent` and `billing_model` — not
`cost_source`, which has no column. `billing_model` is enough for local
rendering to reconstruct the same distinction `cost_source` carries on the
wire, without a redundant third column. Both `upsert_stats` (ingest's
default write path) and `upsert_event` (the `sqlite_local` sink) carry the
two columns, unlike host/workload's known asymmetry under ADR-037 — the
whole point of stamping `billing_model` is that it must reach `lh status`
by default, not only when `sqlite_local` is explicitly configured.

## Alternatives considered

| Option | Why not |
|---|---|
| Billing model on the agent, not the profile | Wrong on this machine's evidence: one agent (`codex`) bills three different ways depending on its auth mode. See Context. |
| Read `~/.codex/auth.json` to infer the billing model | ADR-045 draws the credential boundary; the harness never reads a credential file to infer anything. |
| Exclude flat-rate profiles from cost views entirely | Hides real usage — the opposite error to `$0.00`, and no smaller. |
| Amortise the subscription fee across the month's sessions | The only option that permits a marginal-cost comparison across agents, but the number is fabricated, mutates retroactively as sessions land, and requires the fee to be declared in config where the harness cannot verify it. |
| Add `billing_model` to `aggregate.DIMENSIONS` | It answers "does this bucket's cost mean anything," not "what should this be grouped by" — conflating the two would let a reader group by it as if it were a fact like `host`, when it is a rendering instruction. |
| Omit `agent` and join against config at read time | Config is mutable and rows are permanent — the same argument ADR-037 made for `host` and `workload`. |

## Consequences

### Inside this repo

- `plugins/contracts.py` — version 3, three fields (`agent`, `billing_model`,
  `cost_source`).
- `core/config.py` — `ProfileEntry.billing_model`, validated in
  `_parse_profiles`; `docs/reference/config.md` row.
- `monitoring/db.py` — `session_stats` gains `agent`/`billing_model` via the
  existing `_migrate_identity_columns` mechanism; both `upsert_stats` and
  `upsert_event` write them; `query_stats` projects them.
- `monitoring/ingest.py` — `ingest_all` resolves `agent_for_profile(...).name`
  and the profile's `billing_model`, passes both to `ingest_profile`; the
  row-building loop uses `cost_for_billing_model` in place of
  `calculate_cost`, and `unknown_models` is driven by `cost_source is None`.
- `monitoring/pricing.py` — `cost_for_billing_model`, beside `calculate_cost`,
  which is unchanged.
- `monitoring/aggregate.py` — `agent` in `DIMENSIONS`/`_STRING_DIMENSIONS`/
  `FILTERABLE`; `Bucket.billing_models`/`all_flat_rate`.
- `monitoring/views/overview.py`, `tokens.py`, `sessions.py` — the `—` /
  *priced only* / JSON `null` rendering rules.
- Sinks: no production change; tests pin the fact.

### Outside this repo

Not sequenced here. A receiver ingesting the wire format sees `agent`,
`billing_model` and `cost_source` as three new keys on an otherwise unchanged
payload — the same tolerant-receiver shape ADR-037's deploy-order section
established for `host`/`workload` applies unchanged.

## Verification

- v1/v2 payload compatibility: `MetricEvent.from_dict` on a literal v1 dict
  (no `host`/`workload`/`agent`/`billing_model`/`cost_source`) and a literal
  v2 dict (host/workload, no v3 keys) both load, defaulting the v3 fields.
- `derive_event_id` is unchanged: two events differing only in `agent` share
  an id.
- The config diagnostic for a misspelled `billing_model` names the bad value
  (`pytest.raises(match="billing_model")`, text includes the misspelling).
- Full load cycle: save → load → save → load, for both a new document and a
  merge onto an existing one.
- `session_stats` migration: a store built without the columns gains them
  with `agent=''`, `billing_model='per_token'` on the pre-existing row.
- A flat-rate row: `cost == 0.0`, `cost_source == "subscription"`, does not
  appear in `unknown_models`. A per-token row with no rate still does. A
  priced per-token row carries `cost_source == "pricing"`.
- Every sink carries a v3 event's three new fields unchanged, including the
  real HTTP POST body the outbox drainer sends.
- Rendering: a store with one `per_token` and one `flat_rate` profile in the
  same period renders the flat-rate row as `—`, not `$0.00`, and its total
  relabelled *priced only*; the JSON form carries `cost: null,
  cost_source: "subscription"` for that group.
