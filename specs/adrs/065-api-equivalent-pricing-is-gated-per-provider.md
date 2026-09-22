# ADR-065: API-equivalent pricing covers Anthropic, gated per provider

**Status:** accepted
**Date:** 2026-09-22
**Implemented:** 2026-09-22 — Anthropic rates reach `price_api_response`, the
evidence gate becomes per-provider and is asserted against the rate tables'
own key arity, the two cache-write TTLs stop being merged before pricing, and
`lazy` and `flex` declare `flat_rate`.
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-061 (billed cost and API-equivalent cost are separate),
ADR-050 (agent and billing model in MetricEvent v3)

## Context

ADR-061 split `billed_cost` from `api_equivalent_cost` and shipped the
equivalent path with OpenAI rates only. It recorded the consequence honestly:
zero priced coverage, pending reader evidence. What it did not anticipate is
that the gap never closed on the Anthropic side and could not, because
`price_api_response` rejects any model absent from the OpenAI rate table
before it looks at evidence at all. Locally that is 2999 of 3087 September
rows — the entire Claude fleet — reported as `unknown_model`.

Underneath, the profiles that run Claude Code never declared a billing model.
`per_token` is the default, so `billed_cost` has been carrying Anthropic list
prices — $7980.80 across `lazy` and `flex` for September — in the column that
means invoiced spend. Both profiles authenticate through OAuth subscriptions;
no API key is present in either environment or either `settings.json`. This is
precisely the counterfactual-as-spend ADR-061 set out to prevent, and it
shipped anyway, because the guard was a default rather than a declaration.

Declaring `flat_rate` on those two profiles alone would delete the figure
instead of relocating it: `cost_for_billing_model` short-circuits before
pricing, and the equivalent path cannot catch what it does not recognise.
The two halves have to move together.

## Decision

`price_api_response` prices Anthropic models from `DEFAULT_PRICING`, the same
table `cost_for_billing_model` consults.

The evidence gate is scoped to the dimensions a provider's rate table is
actually keyed on, rather than applied uniformly. OpenAI rates key on
`(model, service_tier, context_class)` within a dated window and keep
requiring every one of them: pricing `gpt-5.6-sol` without a context class is
a coin flip between $4 and $8 per million input tokens. Anthropic publishes
one rate per model — no service tier, no context class, no long-context
surcharge — so there is no dimension left to evidence and none is demanded.
ADR-061's rule was right; its scope was the whole function when it belonged
to one table.

That scoping is structural, not a comment. Each provider declares the
dimensions it requires, and a test asserts the declaration against the arity
of its rate table's own keys. An Anthropic rate that later gains a tier turns
that test red instead of quietly pricing every row at the wrong one — the
failure mode a prose carve-out would have shipped the day the assumption
expired.

The two cache-write TTLs stop being merged before pricing. Anthropic bills a
one-hour write at 2x base input and a five-minute write at 1.25x; ingest held
both counts and summed them into one bucket, which prices every one-hour write
at 62.5% of its rate. `calculate_cost` already separates them, so the merge
was discarding a distinction the table downstream was ready to honour.

`lazy` and `flex` declare `billing_model = "flat_rate"`. That is config, not
code, and it is the half that makes the other half truthful.

## Alternatives considered

Dropping the context-class requirement globally is the smallest edit and
misprices `gpt-5.6-sol` by 2x without saying so. Leaving `billed_cost` as the
Claude list-price proxy is what ships today, and is the presentation ADR-061
rejected. Moving `lazy-codex` to `per_token` to surface a comparison figure
was already rejected in ADR-061 as a lie about the billing model, and yields
nothing regardless: `DEFAULT_PRICING` holds no `gpt-*` rows, so
`calculate_cost` returns `0.0` and `cost_source` `None`. Teaching the
Anthropic reader to report a context class invents a dimension the vendor does
not bill on.

## Consequences

- Billed cost reads `—` for all three profiles. API-equivalent carries the
  comparison figure. This is the pairing ADR-061 designed, holding real
  numbers for the first time.
- September's local total moves column rather than vanishing; re-ingest
  backfills history, since ingest re-reads transcripts rather than advancing
  past them.
- ADR-061's "reader evidence for both dimensions is required" narrows to the
  dimensions each provider's table keys on. Its decision — two independent
  nullable measures, each with source and status — stands unchanged.
- `unknown_model` stops being the answer for the majority of rows, which
  restores it as a signal worth reading.
