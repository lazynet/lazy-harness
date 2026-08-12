# Composable token / cost breakdown for `lh status tokens`

**Status:** accepted
**Date:** 2026-08-12

## Problem

`lh status tokens` can group by exactly one of `project`, `model`, or `profile`,
and always crosses that choice against the model implicitly. The period is a
filter drawn from a fixed set of four values, never a breakdown dimension. There
is no way to ask the questions people actually ask of a cost table:

- What did each profile cost this month, as one number per profile?
- How is spend trending month over month?
- What did Opus specifically cost me, across every project?

There is also no machine-readable output, so any question the table does not
answer has to be answered by hand against SQLite.

Users looking for cost analytics tend to land on `lh metrics status` first,
which is not an analytics command at all — it reports sink delivery state
(pending / sending / sent in the outbox) and prints one summary line as a
header. That command is out of scope here and does not change.

## Constraints

- `session_stats` already carries every field required: `profile`, `project`,
  `model`, `date`, the four token buckets, and `cost`. No schema change, no
  re-ingest, no migration.
- `date` is stored as `YYYY-MM-DD` text.
- The existing table output is the reference look; this extends it rather than
  replacing it.

## Approach

Split the aggregation out of the view, then make both dimensions and period
first-class inputs to it.

### `lazy_harness.monitoring.aggregate` (new module, no Rich)

```python
DIMENSIONS = ("profile", "project", "model", "day", "week", "month")

resolve_period(spec: str) -> Period          # Period(period, since, label)
aggregate(rows, dimensions, filters) -> Aggregation
```

`views/tokens.py` currently reaches into `views/sessions.py` for two private
helpers (`_period_label`, `_query_for_period`). That import is the signal that
this logic wants its own module. Both move here; `sessions.py` imports them
back from `aggregate`.

Keeping the module Rich-free is what lets the table and the JSON output be fed
from one `Aggregation` instead of two parallel aggregation paths that drift.

**Period parsing.** `resolve_period` accepts four shapes:

| Spec | Resolves to | Label |
|---|---|---|
| `today` | `period=<today>` | `Today` |
| `week` | `since=<today-7d>` | `Last 7 days` |
| `month` | `period=<YYYY-MM>` | `<Month> <YYYY>` |
| `all` | `period="all"` | `All time` |
| `<N>d` | `since=<today-Nd>` | `Last N days` |
| `YYYY-MM` / `YYYY-MM-DD` | `period=<spec>` | the spec itself |

The `LIKE '<period>%'` query already supports arbitrary date prefixes; only the
`click.Choice` on the CLI blocked them.

**Temporal dimensions** derive from `date` without a full parse where possible:

| Dimension | Derivation | Example |
|---|---|---|
| `day` | `date` | `2026-08-12` |
| `month` | `date[:7]` | `2026-08` |
| `week` | ISO week via `isocalendar()` | `2026-W33` |

**Filters** (`profile`, `project`, `model`) are case-insensitive substring
matches applied to rows before grouping. `--model opus` matches both
`claude-opus-5` and `claude-opus-4-8`; `--project lazy` matches `lazy-harness`
and `lazy-knowledge`. This trades away exact matching deliberately: the model
strings are long enough that requiring them in full defeats the purpose.

**Grouping** walks `dimensions` in the order given, so the flag order is the
column order. Each group accumulates the four token buckets, `cost`, and a
`sessions` count (distinct `session`). Derived at read time:

- `input` = `input + cache_read + cache_create` (matches today's behaviour)
- `cache_pct` = `cache_read * 100 / input`, `0` when `input == 0`

**Subtotals** are emitted for each distinct value of the *first* dimension, and
only when two or more dimensions are present — with a single dimension they
would restate the rows.

**Rounding happens once, at presentation.** Today `_aggregate` rounds each
group's cost to 2 decimals and `render` sums the rounded values, so the printed
total drifts from `db.aggregate_costs()` — $7929.57 against $7904.31 on a real
database with 16 groups. Accumulating in full precision and rounding only the
emitted figure removes the drift.

### `lazy_harness.monitoring.views.tokens` (now render-only)

`render_table(aggregation, console)` and `render_json(aggregation, console)`,
both consuming the same `Aggregation`.

### `lh status tokens` flags

| Flag | Behaviour |
|---|---|
| `--by DIM` | Repeatable. Order of flags is order of columns. Default: `--by project --by model`. |
| `--period SPEC` | Free-form string, parsed by `resolve_period`. Default `month`. |
| `--profile NAME` | Substring filter. |
| `--model NAME` | Substring filter. |
| `--project NAME` | Substring filter. |
| `--json` | Emit JSON instead of the table. |

An unknown `--by` value fails via `click.Choice` with the valid list, exit 2.

### Output

```
lh status tokens --by profile --by model --period month

By: profile › model | Period: August 2026 | 412 sessions

 Profile  Model              In      Out   Cache%      Cost
 flex     claude-opus-4-8  3.3G    23.1M     96%   $2871.14
 flex     claude-sonnet-5  264M     495K     95%     $84.48
 ─ flex                    3.6G    23.6M     96%   $2955.62
 lazy     claude-opus-5    1.9G     7.2M     98%   $1350.81
 lazy     claude-sonnet-5  658M     3.6M     93%    $265.66
 ─ lazy                    2.6G    10.8M     97%   $1616.47
 ═ Total                   6.2G    34.4M     96%   $4572.09
```

JSON shape:

```json
{
  "period": {"spec": "month", "label": "August 2026", "since": null},
  "dimensions": ["profile", "model"],
  "filters": {"profile": "lazy"},
  "groups": [
    {
      "key": {"profile": "lazy", "model": "claude-opus-5"},
      "input": 1934500000, "output": 7200000,
      "cache_read": 1800000000, "cache_create": 90000000,
      "cache_pct": 98, "cost": 1350.81, "sessions": 412
    }
  ],
  "subtotals": [{"key": {"profile": "lazy"}, "...": "same fields"}],
  "total": {"...": "same fields, no key"}
}
```

`subtotals` is `[]` when fewer than two dimensions are requested.

## Behaviour change

`--by profile` used to return profile × model. It now returns profile alone.
The no-flag default (`project`, `model`) reproduces today's output, so only
callers passing `--by` explicitly are affected. Ships as `feat:` with the CLI
reference updated in the same commit.

## Testing

`tests/monitoring/test_aggregate.py` (new):

- each dimension in isolation, including the three temporal derivations
- a three-dimension combination, asserting column order follows flag order
- subtotal emission: present at two dimensions, absent at one
- each filter, including a case-insensitive substring hit and a miss
- every `resolve_period` shape from the table above
- **the aggregated total equals `db.aggregate_costs()["total_cost"]`** over the
  same fixture — this is the rounding regression, and it is the reason the
  module exists separately from the view

`tests/integration/test_status_views.py` (extended):

- every new flag through `CliRunner`
- `--json` output parses with `json.loads` and carries the documented keys
- an invalid `--by` value exits non-zero

## Out of scope

- `lh metrics status` — remains the sink delivery view, unchanged.
- `lh status costs` — legacy, unchanged.
- Schema, ingest, and pricing.

## Documentation

- `docs/reference/cli.md` — full flag table for `lh status tokens`.
- `docs/how/cost-reporting.md` — new page: the questions the command answers and
  the invocation for each, plus the JSON contract.
