# Codex pricing evidence — 2026-09-19

## Local observation

`lh status tokens --period 2d --profile lazy-codex --by model --json` reported
53 sessions, 329,086,779 input tokens, 161,709,312 cached-input tokens and
562,691 output tokens. Every cost was `null` with source `subscription`.

| Model | Sessions | Input | Cached input | Output |
|---|---:|---:|---:|---:|
| `codex-auto-review` | 18 | 63,770,008 | 30,875,136 | 43,685 |
| `gpt-5.6-sol` | 29 | 264,994,142 | 130,690,944 | 518,767 |
| `gpt-6-astra` | 6 | 322,629 | 143,232 | 239 |

The fixtures in `specs/gates/fixtures/codex-pricing/` retain only one
`turn_context` and one `token_count` record per observed model. Session IDs,
timestamps, prompts, tool calls and responses were removed. They establish
that pricing can use `last_token_usage` per response and carry the preceding
`turn_context.payload.model`; they are not whole-session estimates.

`input_tokens` and `cached_input_tokens` are separate fields in the native
record. Equivalent cost must not subtract one from the other unless a future
binary probe proves Codex changed that wire contract.

## Public price snapshot

The OpenAI API pricing page was read on 2026-09-19:
<https://developers.openai.com/api/docs/pricing>. Standard-tier list prices per
million tokens were:

| Model / context class | Input | Cached input | Cache write | Output |
|---|---:|---:|---:|---:|
| `gpt-5.6-sol`, short | $4.00 | $0.40 | $5.00 | $20.00 |
| `gpt-5.6-sol`, long | $8.00 | $0.80 | $10.00 | $30.00 |
| `gpt-6-astra`, short | $10.00 | $1.00 | $12.50 | $50.00 |
| `gpt-6-astra`, long | $20.00 | $2.00 | $25.00 | $75.00 |

The page also described promotional pricing for `gpt-5.6-sol` through at
least 2026-11-21. The implementation must snapshot effective dates and the
chosen service tier instead of treating today's table as timeless.

No public price row was found for `codex-auto-review`. It stays unpriced; an
alias would fabricate evidence. The short/long boundary was not established
by this capture either. Until an official rule or API response supplies it, a
response that needs the split is `unknown_tier`, not silently short-priced.

