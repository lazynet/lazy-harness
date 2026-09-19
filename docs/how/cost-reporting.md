# How to read token and cost reporting

Once `lh metrics ingest` has populated the metrics database, `lh status tokens`
is the command that answers questions about it. This page walks through the
questions it is built for and the exact invocation for each.

If the numbers look empty or stale, the problem is upstream — see
[Metrics ingest](metrics-ingest.md) for how rows get into the database in the
first place.

!!! note "`lh status tokens` vs `lh metrics status`"
    These sound alike and do different things. `lh status tokens` reports billed
    spend separately from an API-equivalent comparison.
    `lh metrics status` reports **delivery**: how many events are queued, in
    flight, or already shipped to each configured remote sink. If you are asking
    "what did this cost", you want `lh status tokens`.

## The two knobs

Everything the command does comes from two independent choices.

**`--by` picks the dimensions you break the numbers down by.** It is repeatable,
and the order you pass the flags is the order of the columns. Available
dimensions: `profile`, `project`, `model`, `host`, `workload`, `agent`, `day`,
`week`, `month`.

`host` is the machine that produced the sessions, stamped by whichever machine
ingested them. `workload` is the label a caller passed to `lh exec --workload`;
interactive sessions have none and group under `unknown`. `agent` is the adapter
that produced the row (`claude-code`, `codex`, `copilot`) — a permanent,
stamped dimension, never re-derived from the profile's current config.

**`--period` picks the rows that get counted at all.** It takes the four
keywords (`today`, `week`, `month`, `all`) plus a rolling window (`30d`), a
calendar month (`2026-04`), or a single day (`2026-04-15`).

The two are orthogonal. `--by month --period all` breaks all of history down by
month; `--by model --period 2026-04` breaks one month down by model.

## Worked examples

### What is each profile costing me?

```bash
lh status tokens --by profile --period all
```

```
By: profile | Period: All time | 3411 sessions

┏━━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
┃Profile   ┃    In ┃   Out ┃ Cache% ┃ Billed cost┃ API-equivalent cost┃
┡━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
│personal  │  3.5G │ 19.8M │    95% │ $2407.45│ —                  │
│work      │  6.8G │ 45.8M │    95% │ $5540.77│ —                  │
├──────────┼───────┼───────┼────────┼─────────┤
│Total     │ 10.3G │ 65.5M │    95% │ $7948.22│ —                  │
└──────────┴───────┴───────┴────────┴─────────┘
```

`In` is the sum of prompt tokens and both cache buckets; `Cache%` is the share
of that figure served from cache reads, which is the number to watch — a high
cache rate is most of what keeps the billed-cost column down. API-equivalent
cost is a separate public-list-price comparison and is never presented as an
invoice.

### How is spend trending, split by profile?

```bash
lh status tokens --by month --by profile --period all
```

Two dimensions, so the table adds a subtotal row per month:

```
┃Month   ┃ Profile  ┃    In ┃   Out ┃ Cache% ┃ Billed cost┃ API-equivalent cost┃
│2026-07 │ personal │ 425M  │  3.4M │    93% │     $271.14│ —                  │
│2026-07 │ work     │  2.2G │ 15.3M │    95% │    $1872.82│ —                  │
│2026-07 │ subtotal │  2.7G │ 18.7M │    95% │    $2143.97│ —                  │
│2026-08 │ personal │  2.3G │ 11.3M │    96% │    $1472.50│ —                  │
│2026-08 │ work     │  1.4G │  7.2M │    97% │     $987.38│ —                  │
│2026-08 │ subtotal │  3.7G │ 18.5M │    96% │    $2459.88│ —                  │
```

Subtotals key on the **first** dimension, so swapping the flag order to
`--by profile --by month` subtotals per profile instead of per month.

### What did one model cost across everything?

```bash
lh status tokens --by project --model opus --period 30d
```

Filters are case-insensitive substring matches, which is what makes this usable
against real model strings — `--model opus` covers `claude-opus-5` and
`claude-opus-4-8` without you typing either in full. The same holds for
`--profile` and `--project`.

A filter narrows the rows; it does not add a column. Combine the two freely:

```bash
lh status tokens --profile work --by week
```

### What did last Tuesday cost?

```bash
lh status tokens --by project --period 2026-04-15
```

### Feeding it to something else

```bash
lh status tokens --by profile --by model --period month --json
```

```json
{
  "period": {"spec": "month", "label": "August 2026", "since": null},
  "dimensions": ["profile", "model"],
  "filters": {},
  "groups": [
    {
      "key": {"profile": "personal", "model": "claude-opus-5"},
      "input": 1934500000,
      "output": 7200000,
      "cache_read": 1800000000,
      "cache_create": 90000000,
      "cache_pct": 98,
      "cost": 1350.81,
      "billed_cost": 1350.81,
      "billed_coverage": {"priced": 1, "rows": 1},
      "api_equivalent_cost": null,
      "api_equivalent_coverage": {"priced": 0, "rows": 1},
      "api_equivalent_statuses": ["unknown_model"],
      "sessions": 412
    }
  ],
  "subtotals": [{"key": {"profile": "personal"}, "cost": 1616.47}],
  "total": {"cost": 4572.09, "sessions": 891}
}
```

`groups`, `subtotals`, and `total` all carry the same measure fields. The
legacy `cost` key remains a billed-cost alias for v3 consumers; new consumers
should use `billed_cost` and `api_equivalent_cost` with their coverage objects.
`key` is
absent on `total` and holds only the first dimension on each subtotal entry.
`subtotals` is an empty list when fewer than two dimensions were requested.

Piped through `jq`, this is the shortest path to a question the table does not
answer:

```bash
lh status tokens --by day --period 30d --json \
  | jq -r '.groups[] | select(.cost > 50) | "\(.key.day) $\(.cost)"'
```

## Flat-rate agents and unknown models

Not every profile is billed per token. `[profiles.<name>] billing_model =
"flat_rate"` (ADR-050) marks a profile whose usage runs against a
subscription — a ChatGPT-plan Codex login, for example — where the
per-token table has nothing to say about cost. `lh status` renders that
distinction rather than guessing past it:

| `billing_model` | Billed cost | API-equivalent cost | billed source |
| --- | --- | --- | --- |
| `per_token` | amount when priced | independently priced or null | `pricing` or `unknown` |
| `flat_rate` | `—` (never `$0.00`) | independently priced or null | `subscription` |

A `flat_rate` row short-circuits billed pricing entirely, so a model with no entry
in `DEFAULT_PRICING` never falls into the `per_token` / no-rate row above —
the subscription already paid for the usage, and reporting `$0.00` would
read as free rather than unmetered. A group or total with partial coverage
prints the priced-row count beside the amount rather than silently presenting
it as complete. API-equivalent pricing is performed per response. The captured Codex
evidence does not establish the official short/long context boundary, so those
responses fail closed as `unknown_tier` until a reader can provide an explicit
context class. None of the shipped transcript readers supplies that class,
so locally ingested API-equivalent cost currently has zero priced coverage:
every amount is null and the CLI shows `—`. The pricing tables alone do not
provide live coverage. `codex-auto-review` has no public price row and remains
`unknown_model`; it is not aliased to another model. The captured Sol table is
valid from 2026-09-19 through its evidenced promotional horizon of 2026-11-21.
Astra was observed only on 2026-09-19, so other Astra dates fail closed.
Missing, malformed, or out-of-window response dates also fail closed instead
of treating a point-in-time snapshot as permanent pricing.

**Codex today**: the reader's `turn_context` line declares `gpt-5-codex`
(measured 2026-09-17), which carries no `DEFAULT_PRICING` entry. The
authoritative source (developers.openai.com/api/docs/pricing, checked
2026-09-17) lists only `gpt-5.3-codex` under "Specialized models" — a
different, newer model id — so there is no rate to cite for `gpt-5-codex`
itself yet. Concretely, today: a `codex` profile with `billing_model =
"flat_rate"` renders `—`; the same profile under `billing_model =
"per_token"` (an API-key login) renders `unknown_models: gpt-5-codex` on
`lh metrics ingest` and `—` is never confused with "priced at zero."

```bash
lh status tokens --by profile
```

```
By: profile | Period: September 2026 | 2488 sessions

┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
┃Profile             ┃     In ┃   Out ┃ Cache% ┃ Billed cost┃ API-equivalent cost┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
│work                │   5.1G │ 22.6M │    97% │    $3212.9│ —                  │
│personal            │   5.4G │ 26.2M │    97% │   $3716.73│ —                  │
│lazy-codex          │ 222.9K │   153 │    43% │          —│ —                  │
├────────────────────┼────────┼───────┼────────┼─────────┤
│Total               │  10.4G │ 48.9M │    97% │ $6929.63 (2/3)│ —              │
└────────────────────┴────────┴───────┴────────┴─────────┘
```

*Measured 2026-09-17 16:55*, `lh 0.71.1`, one month of real data across all
three profiles — `lazy-codex` renders `—`, never `$0.00`, exactly as
described above, now shown next to two real per-token profiles instead of
standing alone.

`lh status overview` and `lh metrics launches` were the two other pieces of
this worked example still marked synthetic; both are measured too, from the
same `lh metrics ingest` run:

```bash
lh status overview
```

```
Profiles  personal* · work · lazy-codex
Projects  personal: 129 · work: 77 · lazy-codex: 1
Sessions  personal: 4 today · 1315 this month · 4013 total
          work: 181 today · 1168 this month · 3907 total
          lazy-codex: 5 today · 5 this month · 5 total
          all:  190 today · 2488 this month · 7925 total
Tokens    personal: 79.0K in · 26.2M out · billed $3716.73 · API-equivalent — (Sep)
          work: 68.4K in · 22.6M out · billed $3212.9 · API-equivalent — (Sep)
          lazy-codex: 126.6K in · 153 out · billed — · API-equivalent — (Sep)
          all: 274.0K in · 48.9M out · billed $6929.63 (2/3) · API-equivalent — (Sep)
Cache     personal: 5.2G read · 116.9M write
          work: 4.9G read · 112.8M write
          lazy-codex: 96.4K read · 0 write
          all:  10.2G read · 229.6M write
Hooks     ✓ personal:session-context  ✓ personal:session-export  ✓ personal:compound-loop  ✓ work:session-context  ✓ work:session-export  ✓ work:compound-loop
Cron      ✓ graphify-update  ✓ knowledge-push  ✓ metrics-ingest  ✓ qmd-context-gen  ✓ qmd-embed  ✓ qmd-sync
Queue     1 pending · 232 done today
```

The panel's `Tokens` row reports raw input only, with both cache buckets
broken out on its own `Cache` row instead — see "Reconciling the numbers"
below for why that makes `personal`'s `79.0K in` look nothing like the `5.4G`
in the table above, and why that is not a bug.

Notice, too, that `Sessions` breaks down by profile here but `lh status
sessions` cannot: that command only takes `--period today|week|month|all`
(measured: `lh status sessions --help`), with no `--profile` filter. `lh
status tokens --profile <name> --by day` is the closest existing substitute
for a per-profile daily view — narrower in period granularity than the
panel's month-to-date line, but the only command that actually accepts a
profile filter. Recorded as an open gap, not fixed here.

```bash
lh metrics launches
```

```
work            claude-code  run    28
personal        claude-code  exec   8
personal        claude-code  run    3
lazy-codex      codex        run    7

work            launches=28 sessions=1404 ratio=0.02
personal        launches=11 sessions=2011 ratio=0.01
lazy-codex      launches=7 sessions=5 ratio=1.40
```

`lazy-codex`'s ratio is `1.40` — above 1, because the ratio is launches over
*ingested sessions* in the window, not a fraction clamped to a session's
lifetime. Several of that day's launches were probes against a throwaway
`CODEX_HOME` that never produced a transcript, so `lh metrics ingest` never
saw a session for them: a launch with no matching session still counts in
the numerator.

## Reconciling the numbers

`lh status tokens`'s `In` column and `lh status overview`'s `Tokens` line
both claim to report input tokens for the same profile and month, and they
disagree on purpose. From the worked examples above, `personal` for
September 2026: the table's `In` is `5.4G`; the panel's `Tokens` line is
`79.0K in`, with `5.2G read · 116.9M write` on its own `Cache` line. The
table's `In` is `input + cache_read + cache_create` (`Bucket.total_input` in
`monitoring/aggregate.py`) — "the sum of prompt tokens and both cache
buckets" from the first worked example above. The panel's `Tokens` row is
raw `input` alone, by design (see the comment above it in
`monitoring/views/overview.py`): it matches how ccusage and Anthropic's own
billing report input, and reporting cache there too would bury the number
that dominates a long session by four or five orders of magnitude. Its
`Cache` row exists precisely so that number is not lost, just kept off the
`Tokens` line.

Adding the panel's three numbers back up: `79.0K + 5.2G + 116.9M ≈ 5.32G` —
visibly short of the table's `5.4G`, and that gap is expected, not a defect:
each of the three figures is independently rounded to one decimal at its own
magnitude (K, M, or G) before display, so summing three already-rounded
numbers does not reproduce a total that was rounded once, from the unrounded
per-token sum, on the table's side. `Out` and `Billed cost` do not have this split —
both views agree on them exactly (`26.2M` and `$3716.73`) — which is the
evidence that the `In` gap is a definition difference, not the two commands
reading different data.

The total printed by `lh status tokens` is computed at full precision and
rounded once, at the end. It reconciles exactly with the database's own sum, so
if you want to check the command against the raw table:

```bash
sqlite3 ~/.local/share/lazy-harness/metrics.db \
  'SELECT ROUND(SUM(cost), 2), COUNT(DISTINCT session) FROM session_stats'
```

Those two figures match the `Total` row and the session count in the header. A
mismatch means the database moved between the two commands — usually an ingest
running in between.
