# ADR-061: Billed cost and API-equivalent cost are separate

**Status:** accepted
**Date:** 2026-09-19
**Implemented:** 2026-09-19 — MetricEvent v4, SQLite migration, response-level
pricing, replay monotonicity and the CLI views ship locally. Receiver and
Grafana deployment remain a separate rollout lane.
The API-equivalent data path is implemented, but shipped transcript readers
do not supply `context_class`: locally ingested `api_equivalent_cost` is
uniformly null today (zero priced coverage).
**Supersedes:** —
**Superseded by:** —
**Amended by:** ADR-065 — the reader-evidence requirement below is
scoped to the dimensions each provider's rate table is keyed on, and
Anthropic rates reach the equivalent path.
**Related:** ADR-050 (agent and billing model in MetricEvent v3)

## Context

Flat-rate profiles have no usage-billed amount, but their token volume still
needs a public list-price comparison. Reusing `cost` would present a
counterfactual as actual spend.

## Decision

MetricEvent v4 and storage carry independent nullable `billed_cost` and
`api_equivalent_cost`, each with source/status. Equivalent pricing happens per
response with versioned provider/model/service-tier/context-class rates.
Unknown models and tiers remain named nulls; `codex-auto-review` is not aliased.

The tables and synthetic priced tests do not establish live coverage. Known
models with usage remain `unknown_tier` until a reader supplies an evidenced
context class; other models remain `unknown_model`. Ingest also currently
passes `service_tier="standard"` without measuring it. Reader evidence for both
dimensions is required before claiming live API-equivalent pricing.

V3 `cost` retains billed semantics. The receiver becomes v4-tolerant before
producers emit it, and identical event IDs upsert without duplication.

## Alternatives considered

Changing Codex to `per_token` lies about its billing model. Overloading `cost`
hides invoice versus comparison semantics. Session-level pricing loses
response-level context classes and effective dates.

## Consequences

- CLI, remote storage and Grafana label both measures.
- Partial coverage stays visible.
- Producer, receiver and dashboard ship in compatibility order.
