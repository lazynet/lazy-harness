# ADR-061: Billed cost and API-equivalent cost are separate

**Status:** proposed
**Date:** 2026-09-19
**Supersedes:** —
**Superseded by:** —
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

