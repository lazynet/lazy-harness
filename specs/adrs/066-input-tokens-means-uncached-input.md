# ADR-066: `TokenUsage.input_tokens` means uncached input

**Status:** accepted
**Date:** 2026-09-22
**Implemented:** 2026-09-22 — the contract names the exclusion, `CodexAdapter`
subtracts the cached half, and the adapter test asserts the arithmetic the
provider's own records satisfy instead of a shape no record can hold.
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-048 (Codex's rollout is two streams), ADR-065 (API-equivalent
pricing is gated per provider), ADR-032 (agent adapter completeness)

## Context

`TokenUsage` documents why each field is nullable and says nothing about what
`input_tokens` counts. Every priced path reads it one way — `calculate_cost`
multiplies `input` by the input rate and `cache_read` by the cache-read rate
and adds them, so the two must be disjoint — but the field never said so, and
the two readers filled the silence differently.

Anthropic reports the halves separately, so `ClaudeCodeAdapter` passing
`input_tokens` through is correct. OpenAI reports `input_tokens` *inclusive*
of `cached_input_tokens`, and `CodexAdapter` passes it through too. Measured
across 92 rollouts and 5893 usage records under `~/.codex-lazy/sessions`:
`total_tokens == input_tokens + output_tokens` held 5893 times with no
exception, and `cached_input_tokens > input_tokens` occurred zero times. The
cached half is a subset of the reported input, never a sibling of it.

The consequence is a 41x overstatement of fresh input on that profile —
642.7M reported against 15.4M actually uncached for September — with the
cached 627.4M billed a second time at the read rate. It has been invisible as
money only because every Codex row is `unknown_tier` or `unknown_model` and so
carries no figure at all; it has been visible all along in the token columns
and in a cache-hit rate of 49% where the same workload on Claude reads 97%.

The adapter test that pinned this mapping used `input_tokens=11` with
`cached_input_tokens=33` and `total_tokens=165`. No Codex record can hold
those numbers. It asserted that the fields are copied, which was never in
doubt, and never that they mean what the pricer assumes.

## Decision

`TokenUsage.input_tokens` is the input the provider charged at full rate:
tokens served from cache are excluded and counted in `cache_read_tokens`. The
docstring says so, because a Protocol field consumed by arithmetic has to
state the arithmetic's premise.

`CodexAdapter` subtracts, clamped at zero. Its test asserts against a record
satisfying the provider's own invariant, and a second test asserts the
invariant itself over the shipped fixtures, so a future record that breaks it
is a failure rather than a silent re-interpretation.

Normalising in the adapter rather than at the pricer keeps one meaning for the
field at the seam every consumer already reads. `cache_read_tokens` keeps
Codex's own number: only the full-rate half was ever ambiguous.

## Alternatives considered

Teaching `calculate_cost` that some providers report inclusive input moves a
provider's wire format into the pricer and leaves every other consumer of
`TokenUsage` — the status views, the exec envelope, the remote sink — reading
the inflated figure. Leaving the field undefined and documenting the Codex
quirk where it is read reproduces the defect for the next adapter, and the
next reader of a rollout is the one who would have to know. Storing both a
gross and a net input doubles the schema to preserve a number no consumer
asked for; `total_tokens` already reconstructs it.

## Consequences

- Codex token totals drop to what was actually charged at full rate, and its
  cache-hit rate becomes comparable to the other profiles.
- The over-count never reached a dollar figure, so no stored cost changes.
  Re-ingest rewrites the token columns.
- When a context class eventually reaches the Codex reader, the figure it
  unlocks is right on arrival rather than 8x high.
- `input_tokens` now carries a premise an adapter can violate, so the
  invariant is asserted rather than assumed.
