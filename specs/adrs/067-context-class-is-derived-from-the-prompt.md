# ADR-067: The context class is derived from the prompt, not awaited from a reader

**Status:** accepted
**Date:** 2026-09-22
**Implemented:** 2026-09-22 — the rate table carries each model's published
long-context threshold, `price_api_response` classifies from the gross prompt
when a caller supplies no class, and `ApiRateTable` separates the dimensions
its keys carry from the ones a caller must evidence.
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-061 (billed and API-equivalent cost are separate), ADR-065
(API-equivalent pricing is gated per provider), ADR-066 (`input_tokens` means
uncached input)

## Context

ADR-061 shipped `unknown_tier` for every Codex row and named the cause: no
shipped reader supplies a `context_class`. ADR-065 kept that gate for OpenAI
on the correct ground that the rates key on the class and differ 2x. Both
recorded the state as waiting on reader evidence.

It was not waiting on evidence. OpenAI publishes the rule on each model page:
"Prompts with >272K input tokens are priced at 2x input and 1.5x output for
the full request" (`gpt-5.6-sol`), and the same 272K on `gpt-6-astra`, where
the wording adds that the cache rates double too. The shipped rate rows already
encode exactly that — every long row is 2x its short counterpart on input,
cached input and cache writes, and 1.5x on output. The threshold was the one
part of the published rule the table left out, and its absence was read as the
vendor being silent.

The class was never a separate observation. It is a function of the prompt
size, and the usage record reports the prompt size. Waiting for a reader to
announce it is waiting for a restatement of a number already in hand.

## Decision

`ApiRateTable` carries `long_context_threshold`, the published boundary, beside
the rates it qualifies. `price_api_response` classifies from the prompt when no
class is supplied, and an explicitly supplied class still wins — a reader that
one day observes the class directly is better evidence than a derivation.

The classification reads the **gross** prompt: the input the provider counted,
cached half included. After ADR-066 the adapter reports input net of cache, so
the pricer reconstructs the gross as `input + cache_read`. This is the trap
worth naming: a 300K prompt served 90% from cache is a long-context request
priced at 2x, and classifying it on the net 30K would call it short. The two
numbers answer different questions — one sizes the prompt, the other is what
gets charged at full rate — and the same record supplies both.

The threshold lives with the rates rather than in the adapter. A reader that
knew 272K would be a second place holding a pricing fact, and the adapter would
have to be revised on a rate change that has nothing to do with transcripts.

`ApiRateTable.dimensions` keeps meaning the dimensions its keys carry, which is
what the arity test checks. A new `required` names the narrower set a caller
must evidence. For OpenAI they now differ: the key carries a context class the
table can derive, so only the service tier is awaited.

## Alternatives considered

Having `CodexAdapter` set the class duplicates a published rate boundary into
an adapter, against the repository's rule that one answer lives in one
importable place. Classifying on the charged input is simpler and wrong for
exactly the cache-heavy prompts this harness produces — the measured corpus
runs 97% cache-read, so it is the common case, not the corner. Leaving the
rows `unknown_tier` keeps a real figure withheld on a premise that checking
the vendor's page disproves.

## Consequences

- Codex rows carrying a rate-window date become priced; `unknown_tier` returns
  to meaning a tier genuinely unevidenced.
- On the measured corpus every request classifies short: the largest observed
  prompt is 244,935 input tokens against a 272K boundary, and Codex reports a
  258,400-token context window, so nothing crosses it today. The long branch is
  reached by test rather than by data, which is the honest state to record.
- `service_tier` stays awaited and stays asserted as `"standard"` by ingest
  without measurement. ADR-061 named that; this decision does not close it, and
  the split between `dimensions` and `required` is where closing it will land.
