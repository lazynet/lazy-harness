# How to read token and cost reporting

Once `lh metrics ingest` has populated the metrics database, `lh status tokens`
is the command that answers questions about it. This page walks through the
questions it is built for and the exact invocation for each.

If the numbers look empty or stale, the problem is upstream — see
[Metrics ingest](metrics-ingest.md) for how rows get into the database in the
first place.

!!! note "`lh status tokens` vs `lh metrics status`"
    These sound alike and do different things. `lh status tokens` reports spend.
    `lh metrics status` reports **delivery**: how many events are queued, in
    flight, or already shipped to each configured remote sink. If you are asking
    "what did this cost", you want `lh status tokens`.

## The two knobs

Everything the command does comes from two independent choices.

**`--by` picks the dimensions you break the numbers down by.** It is repeatable,
and the order you pass the flags is the order of the columns. Available
dimensions: `profile`, `project`, `model`, `day`, `week`, `month`.

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
┃Profile   ┃    In ┃   Out ┃ Cache% ┃     Cost┃
┡━━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
│personal  │  3.5G │ 19.8M │    95% │ $2407.45│
│work      │  6.8G │ 45.8M │    95% │ $5540.77│
├──────────┼───────┼───────┼────────┼─────────┤
│Total     │ 10.3G │ 65.5M │    95% │ $7948.22│
└──────────┴───────┴───────┴────────┴─────────┘
```

`In` is the sum of prompt tokens and both cache buckets; `Cache%` is the share
of that figure served from cache reads, which is the number to watch — a high
cache rate is most of what keeps the cost column down.

### How is spend trending, split by profile?

```bash
lh status tokens --by month --by profile --period all
```

Two dimensions, so the table adds a subtotal row per month:

```
┃Month   ┃ Profile  ┃    In ┃   Out ┃ Cache% ┃     Cost┃
│2026-07 │ personal │ 425M  │  3.4M │    93% │  $271.14│
│2026-07 │ work     │  2.2G │ 15.3M │    95% │ $1872.82│
│2026-07 │ subtotal │  2.7G │ 18.7M │    95% │ $2143.97│
│2026-08 │ personal │  2.3G │ 11.3M │    96% │ $1472.50│
│2026-08 │ work     │  1.4G │  7.2M │    97% │  $987.38│
│2026-08 │ subtotal │  3.7G │ 18.5M │    96% │ $2459.88│
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
      "sessions": 412
    }
  ],
  "subtotals": [{"key": {"profile": "personal"}, "cost": 1616.47}],
  "total": {"cost": 4572.09, "sessions": 891}
}
```

`groups`, `subtotals`, and `total` all carry the same measure fields. `key` is
absent on `total` and holds only the first dimension on each subtotal entry.
`subtotals` is an empty list when fewer than two dimensions were requested.

Piped through `jq`, this is the shortest path to a question the table does not
answer:

```bash
lh status tokens --by day --period 30d --json \
  | jq -r '.groups[] | select(.cost > 50) | "\(.key.day) $\(.cost)"'
```

## Reconciling the numbers

The total printed by `lh status tokens` is computed at full precision and
rounded once, at the end. It reconciles exactly with the database's own sum, so
if you want to check the command against the raw table:

```bash
sqlite3 ~/.config/lazy-harness/metrics.db \
  'SELECT ROUND(SUM(cost), 2), COUNT(DISTINCT session) FROM session_stats'
```

Those two figures match the `Total` row and the session count in the header. A
mismatch means the database moved between the two commands — usually an ingest
running in between.
