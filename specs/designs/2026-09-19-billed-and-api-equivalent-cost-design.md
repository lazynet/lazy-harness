# Billed and API-equivalent cost design

**Status:** proposed  
**Date:** 2026-09-19  
**Decision:** [ADR-061](../adrs/061-billed-cost-and-api-equivalent-cost-are-separate.md)

## Problem

ADR-050 correctly prevents flat-rate usage from being reported as an invoice.
It short-circuits pricing to zero with `cost_source="subscription"`, then views
hide that zero. Grafana still aggregates generic `cost`, so Codex volume has no
useful price comparison and can look free.

The comparison wanted is hypothetical: public API list price for the observed
tokens. It must not overwrite billed-cost semantics.

## Data contract

MetricEvent v4 and `session_stats` carry two measures:

| Field | Meaning | Subscription value |
|---|---|---|
| `billed_cost` | variable amount attributable to usage | `null` |
| `billed_cost_source` | `pricing`, `subscription`, `unknown` | `subscription` |
| `api_equivalent_cost` | public API list-price comparison | number or `null` |
| `api_equivalent_status` | `priced`, `unknown_model`, `unknown_tier`, `no_usage` | independent |
| `api_price_basis` | provider, service tier, currency, rate-table version | required when priced |

V3 `cost` and `cost_source` remain readable during migration and map only to
the billed side. Renderers never label either measure merely `Cost`.

## Pricing unit

Equivalent cost is computed per response from native `last_token_usage`, then
summed into `(profile, session, model)`. Aggregating tokens first is wrong when
short and long context classes coexist or a rate changes by effective date.

Rates are keyed by provider model ID, service tier, context class and effective
date. Wave 1 supports only OpenAI `standard`; Batch, Flex and Fast are distinct
bases. Missing model or unresolved context class yields a null plus status.

`reasoning_output_tokens` is already within output and is not added again.
Cached input remains its own bucket. Evidence and sanitized fixtures live in
[`2026-09-19-codex-pricing-evidence.md`](2026-09-19-codex-pricing-evidence.md).

## Pipeline and rollout

1. Make pricing return a typed result where absence cannot collapse to zero.
2. Preserve response-level price and basis through ingest; aggregate money.
3. Add SQLite columns and backfill v3 billed semantics without fabricating
   equivalents.
4. Deploy a v3/v4-tolerant receiver before producers emit v4; retain event IDs
   so replay enriches rather than duplicates.
5. Re-ingest transcripts, drain the outbox, then split CLI and Grafana into
   `Billed cost` and `API-equivalent cost` with coverage beside the latter.

Grafana lives in a separate repository and is a distinct deployment lane.

## Acceptance gates

- Golden tests price the two public model IDs and leave `codex-auto-review` as
  `unknown_model`.
- A mixed short/long session proves price-before-aggregation; this stays
  blocked until the official boundary is captured.
- A flat-rate row has `billed_cost=null` and may have a numeric equivalent; no
  renderer turns null into `$0.00`.
- Receiver replay of one v3 then v4 event ID leaves one remote row.
- Grafana keeps token volume visible when equivalent coverage is partial.

Rollback stops v4 emission. Additive columns remain readable and v3 consumers
continue using legacy billed fields.

