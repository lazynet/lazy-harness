# ADR-070: Anthropic prompt-length pricing is classified per response and stored per session

**Status:** accepted
**Date:** 2026-10-07
**Implemented:** 2026-10-08 — `claude-haiku-5-5` is priced at its short and long
prompt-length tiers per response, ingest and `session_cost_from_disk` price each
class bucket before summing, the Anthropic rate table declares `context_class`,
the `claude-sonnet-5-5` cache read is corrected to $0.10, and a test pins the
Claude Code alias targets.
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-050 (billing model), ADR-061 (billed and API-equivalent cost
are separate), ADR-065 (API-equivalent pricing is gated per provider), ADR-066
(`input_tokens` means uncached input), ADR-067 (the context class is derived
from the prompt)

## Context

Claude Code's `haiku` alias resolves to `claude-haiku-5-5` today. Probed on
2026-10-07 with Claude Code 2.1.293, `claude -p --model <alias> --output-format
json` reports `modelUsage` keys `claude-haiku-5-5`, `claude-sonnet-5-5` and
`claude-opus-5-5` for `haiku`, `sonnet` and `opus`. The `fast` tier
(`agents/claude_code.py:54`), Agent subagents and orchestrated panes run on
`haiku`, so those runs all use Haiku 5.5. `DEFAULT_PRICING` has no row for it.
`price_api_response("claude-haiku-5-5", ...)` returns `unknown_model`
(run on 2026-10-07), and `calculate_cost` returns `0.0`.

Anthropic's pricing page (platform.claude.com/docs/en/about-claude/pricing,
read 2026-10-07) prices Haiku 5.5 in two rows:

| Haiku 5.5 | Base input | 5m write | 1h write | Cache hit | Output |
| --- | --- | --- | --- | --- | --- |
| prompts up to 100,000 tokens | $0.10 | $0.125 | $0.20 | $0.01 | $0.50 |
| prompts over 100,000 tokens | $0.50 | $0.625 | $1 | $0.05 | $2.50 |

"Claude Haiku 5.5 is priced by prompt length: a prompt of over 100,000 tokens
pays higher prices." Every other current model is priced flat: "Claude 4.6 and
later models (except Claude Haiku 5.5) [...] include the full 1M token context
window at standard pricing." Output and both cache-write rates are in the
long-prompt row too, so the whole request pays the higher rate. The prompt is
defined on the context-windows page: "the input count is split across
`input_tokens`, `cache_read_input_tokens`, and `cache_creation_input_tokens`,
and all three count toward the window."

The same page also shows a bug that already ships. Sonnet 5.5's cache hit is
"$0.10 / MTok", and "Cache hits and refreshes on Claude Opus 5.5 and Claude
Sonnet 5.5 are priced at 0.05x the base input price." The `claude-sonnet-5-5`
row in `pricing.py` carries `cache_read: 0.2`, so every Sonnet 5.5 cache read
is charged at twice its price. The row was a copy of `claude-sonnet-5`, which
is the mistake the `claude-opus-5-5` comment warns about.

### Where tokens are available, path by path

The prompt-length boundary applies to one request, but the stored row covers
one session. A session whose summed prompt tokens exceed 100K is not a long
prompt. Each pricing path was checked to find where per-request tokens still
exist:

| Path | Granularity it prices at today | Evidence |
| --- | --- | --- |
| `ClaudeCodeAdapter.read` | yields one `TOKEN_USAGE` event per assistant message, with that message's `usage` | `agents/claude_code.py:1037-1056`; `context_class` is never set for Claude (`agents/base.py:470`, the only other hit is the ingest read) |
| Ingest, API-equivalent | **per response**: `price_api_response` is called inside the event loop | `monitoring/ingest.py:244` |
| Ingest, billed cost | **per session**: `cost_for_billing_model` runs over the `(session, model)` sum after the loop | `monitoring/ingest.py:280`, aggregation at `:213-229` |
| `lh exec` cost | **per session**: `session_cost_from_disk` sums per model, then calls `calculate_cost` | `monitoring/collector.py:259`, called from `cli/exec_cmd.py:163` |
| `parse_session` | per session; tests are its only caller | `monitoring/collector.py:141`; `grep` finds no caller in `src/` |
| Sinks | do not price; they ship the `MetricEvent` ingest built | `monitoring/ingest.py:339-381`; `sinks/sqlite_local.py:30` writes it as-is |
| `statusline` | does not price; reads Claude Code's own `cost.total_cost_usd` | `monitoring/statusline.py:116` |

Only one pricing path keeps per-request tokens. Every path reads them, though:
each reader walks one assistant message at a time before summing.

The real transcripts show why session-level classification is wrong. Every
`*.jsonl` under `~/.claude-lazy/projects` and `~/.claude-flex/projects` was
scanned on 2026-10-07, deduplicated by `message.id`. The prompt is
`input + cache_read + cache_creation`:

| Model | Responses | Responses over 100K | Sessions | Sessions whose **sum** exceeds 100K |
| --- | --- | --- | --- | --- |
| `claude-haiku-4-5-20251001` (the `haiku` workload until now) | 4,022 | 4 | 2,553 | 116 |
| `claude-haiku-5-5` | 1 | 0 | 1 | 0 |

If Haiku traffic keeps that shape, session-sum classification would bill 116
sessions at 5x when 4 requests in them crossed the boundary. The one Haiku 5.5
response so far is `input_tokens: 2`,
`cache_creation_input_tokens: 47,703` (all of it 1-hour), `cache_read: 0`.
Nearly the whole prompt is a cache write. ADR-067's OpenAI gross is
`input + cache_read`, which would undercount it, and with Anthropic usage it
undercounts on every request that writes cache. Of the 4 Haiku 4.5 requests
over 100K, one is over only once its cache writes are counted.

## Decision

1. **Anthropic prompt-length rates live in their own table, next to the
   standing rates.** `DEFAULT_PRICING` keeps one row per model, the rate for
   short prompts. A new `LONG_CONTEXT_PRICING: dict[str, LongContextRate]`
   holds, for each model the vendor prices by prompt length, the threshold and
   the higher rates. `claude-haiku-5-5` is the only entry. This follows
   `INTRODUCTORY_PRICING`: one exception table keyed by model, and a config
   override of a model's row is final. A model whose short row was overridden
   in `[monitoring.pricing]` is never switched to the shipped long rates.

2. **The class is decided per response from Anthropic's prompt.**
   `anthropic_context_class(model, tokens)` returns `"long"` when
   `input + cache_read + cache_create + cache_create_1h` exceeds the model's
   threshold. The comparison is strict, matching "over 100,000". A model with
   no `LONG_CONTEXT_PRICING` entry is always `"short"`, because the vendor
   publishes flat pricing for it. The buckets differ from OpenAI's on purpose.
   Anthropic reports cache writes alongside `input_tokens`, while OpenAI counts
   them inside its input figure (ADR-066/067). The gross is reconstructed from
   what each provider leaves out of its input figure.

3. **Pricing paths split the tokens by class, not by request.** Ingest and
   `session_cost_from_disk` still aggregate, but per
   `(session, model, context_class)`. Each class bucket is priced at its own
   rates and the buckets are added up. The per-token rates are linear, so this
   gives the same result as pricing each response, with one rounding per
   bucket instead of one per response. `calculate_cost` and
   `cost_for_billing_model` gain a keyword `context_class` (default
   `"short"`). Callers classify each response before summing.

4. **Rows stay per session.** `session_stats`, `MetricEvent` and the sink
   payload still carry one row per `(session, model)` with summed tokens and
   a summed cost. The class split exists only until the price is computed,
   the same rule the cache-write TTL split follows
   (`docs/how/metrics-ingest.md`, "Cache writes are priced by TTL"). There is
   no schema migration or wire-format change.

5. **The Anthropic rate table declares the dimension.** `API_RATE_TABLES
   ["anthropic"]` is keyed `(model, context_class)` and declares
   `dimensions=("context_class",)` with `required=()`. The class is derived
   from the usage record, never awaited, as in ADR-067. A flat-priced model
   has identical `short` and `long` rows. The arity test
   (`test_each_rate_table_declares_the_dimensions_its_keys_carry`) then covers
   a declaration that ADR-065 left empty because no Anthropic model was priced
   by prompt length. `price_api_response` prices an Anthropic response with
   the class the reader supplies, or the derived one. It computes the amount
   from the same rate selection `calculate_cost` uses, but without the
   six-decimal rounding. At $0.01/MTok for cache hits, rounding per response
   loses sub-micro amounts that OpenAI responses already keep
   (`test_api_equivalent_keeps_sub_micro_response_costs`). Measured on
   2026-10-07: a one-token Opus 5 cache read prices at `0.0`.

6. **`claude-sonnet-5-5` reads at $0.10.** The row is corrected, and so is the
   test that pinned the wrong value (`test_default_pricing_includes_sonnet_5_5`).

7. **The alias targets are pinned by a completeness test.** A test-only map
   records what each Claude Code alias resolved to on the probe date. It
   asserts that each target has a `DEFAULT_PRICING` row. When the alias
   changes, the next probe updates the map, and the test fails until the new
   model has a row.

## Alternatives considered

- **Classifying the session sum.** It is the shortest change and the one the
  stored shape suggests. It is wrong for 116 of 2,553 measured Haiku sessions
  and charges them 5x.
- **Storing one row per `(session, model, context_class)`.** It keeps
  information no reader consumes today, and it changes `UNIQUE(session,
  model)`, the upsert, the event id derivation and the wire format. If a view
  ever needs the split, it can be added then, the same reasoning that kept
  the TTL split out of the schema.
- **Pricing every response and summing the rounded amounts.** It is as exact
  as decision 3 in principle, but it rounds once per response, and Haiku 5.5's
  rates make that rounding a measurable share of the total.
- **Giving `ApiRateTable` one `long_context_threshold` for Anthropic.** It
  works while one model has a boundary. It encodes a provider-wide threshold
  that the vendor does not publish, so a second model with a different
  boundary would silently get Haiku's.
- **Long rates as a second `DEFAULT_PRICING` key (`claude-haiku-5-5@long`).**
  It would invent a model id that no transcript carries, and
  `cost_for_billing_model`'s `model in pricing` check would report it as a
  known model.

## Consequences

- **Already-ingested rows are repriced by the next ingest, as long as their
  transcripts still exist.** Ingest re-reads every transcript on every run.
  `get_ingest_mtime` and `set_ingest_mtime` have no caller outside
  `monitoring/db.py` and its tests. `upsert_stats` overwrites cost columns
  when the incoming `event_schema_version` is the same or newer
  (`monitoring/db.py:456-497`). Verified by running it on 2026-10-07: on a
  copy of the live `metrics.db`, `ingest_all` with `claude-sonnet-5-5`
  `cache_read` patched to `0.1` moved that model's summed
  `api_equivalent_cost` from 182.50 over 328 rows to 141.07 over 339 rows (the
  run also picked up new sessions). The affected rows date from 2026-09-28
  onward. The oldest transcript on disk is from 2026-09-07, so all of them can
  still be repriced. A row whose transcript has been pruned keeps its old
  value. Ingest must run after the deploy, before about 2026-10-28.
- **The remote sink receives the corrected events.** `outbox_enqueue` sets a
  row back to `pending` when its payload changed (`monitoring/db.py:958-964`).
  The repriced `api_equivalent_cost` therefore ships again under the same
  event id.
- **The impact is on the API-equivalent column, not billed cost.** Both local
  profiles are `flat_rate`. Their billed `cost` stays `0.0` with
  `billed_cost_source = subscription`, before and after this change. Measured
  on the DB copy, the one Haiku 5.5 row is `api_equivalent_status =
  unknown_model` with a null amount. The Sonnet 5.5 rows are overstated by
  0.10 USD per million cache-read tokens, 43.5 USD over the 434.6M reads
  stored.
- **`unknown_models` would not have caught this.** It fires only for a
  `per_token` row with no rate (`monitoring/ingest.py:298`), so a `flat_rate`
  profile never reports a missing model there. On the live config,
  `ingest_all` returned an empty `unknown_models` while the Haiku 5.5 row was
  `unknown_model`. The completeness test in decision 7 is the guard that
  works for these profiles.
- **Two documents are already wrong, and the implementation fixes them.**
  `docs/reference/cli.md` says ingest "tracks each session's file mtime [...]
  and skips files that haven't changed". No code path does that.
  `docs/how/cost-reporting.md` says API-equivalent cost "currently has zero
  priced coverage", which ADR-065 and ADR-067 made untrue.
  `docs/how/metrics-ingest.md` gives cache reads a single 0.1x multiplier,
  which is wrong for three published exceptions.
- **Out of scope, recorded here.** 4 of 84,967 Claude Code usage records
  carry more than one entry in `usage.iterations` (a `fallback_message` served
  by a second model). The reader prices only the top-level `usage` under
  `message.model`. The compound-loop distiller's default model is still the
  dated `claude-haiku-4-5-20251001` (`llm/claude.py:21`, `core/config.py:263`).
  That choice is separate and is left as it is.
