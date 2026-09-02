# ADR-012: Monitoring uses a local SQLite store populated from session JSONL

**Status:** accepted
**Date:** 2026-04-13

## Context

Running an agent as a daily driver quickly raises the question "how much did this cost, and what was it spent on?". Claude Code does not expose aggregate stats; it writes session JSONLs and trusts the user to make sense of them. We need:

- Token counts per session (input, output, cache read, cache create), per model, with cost computed from a pricing table.
- Aggregation by day, project, profile, model.
- Multiple viewing angles (by project, by profile, by session, hooks log, scheduler, memory usage) without rebuilding the pipeline each time.
- Cheap queries — `lh status` is something the user runs casually, it cannot wait five seconds.
- No network dependency. The data is already local, on disk, in every `~/.claude/projects/*/**.jsonl`.

## Decision

**A local SQLite database (`monitoring/db.py`) populated by a collector that parses session JSONLs (`monitoring/collector.py`), plus a small set of view modules (`monitoring/views/`) that render aggregated output.**

Schema as decided on 2026-04-13 — a single table, intentional. It has since grown;
`src/lazy_harness/monitoring/db.py` is the source of truth, and the *Evolution* section
below records what changed and why:

```sql
CREATE TABLE session_stats (
    session       TEXT NOT NULL,
    date          TEXT NOT NULL,
    model         TEXT NOT NULL,
    profile       TEXT NOT NULL DEFAULT '',
    project       TEXT NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read    INTEGER NOT NULL DEFAULT 0,
    cache_create  INTEGER NOT NULL DEFAULT 0,
    cost          REAL NOT NULL DEFAULT 0.0,
    UNIQUE(session, model)
);
CREATE INDEX idx_stats_date ON session_stats(date);
```

The `UNIQUE(session, model)` constraint makes re-ingestion idempotent: running the collector against a session that already has stats is a no-op via `INSERT OR IGNORE`. Every view is a parametric SQL query, not a derived table.

Pricing lives in `config.toml` under `[monitoring.pricing]`, a dict keyed by model name with input/output/cache-read/cache-create rates. `pricing.py` computes cost on ingest, not on query — the cost column is a materialized result so views never touch pricing.

Views under `monitoring/views/` each render a distinct slice (`overview`, `projects`, `profiles`, `sessions`, `tokens`, `cron`, `hooks`, `memory`, `queue`). Each view is a self-contained module exposing a render function called from `monitoring/dashboard.py` and `cli/status_cmd.py`.

## Alternatives considered

- **Read session JSONLs on every `lh status` call.** Works for one or two projects, degrades linearly with history. Rejected — `lh status` would become the slowest command in the CLI.
- **Postgres / DuckDB / an external database.** Overkill for a per-user local tool. SQLite is stdlib, zero-install, and handles this workload without noticing it.
- **Multiple normalized tables (`sessions`, `models`, `projects` with foreign keys).** The only join we would ever need is `GROUP BY project` or `GROUP BY model`, both of which are single-column aggregations. Normalization would cost complexity without buying anything measurable.
- **Append-only log files per day.** Loses SQL, loses indexes, loses the `UNIQUE` idempotence guarantee. Rejected.
- **Stream stats directly from a hook (write row per event).** Couples monitoring ingestion to every tool call, failing the "hook exits in milliseconds" budget and making the hook pipeline responsible for a responsibility that belongs to a batch job. Kept as a collector that runs on demand instead.

## Consequences

- `lh status` is instant on any reasonable history size. The indexed `date` column and single-table queries keep every view under 50ms.
- The database file lives at `~/.config/lazy-harness/metrics.db` by default (overridable). It is user-owned and survives uninstalls, consistent with the other persistent stores ([ADR-001](001-hybrid-architecture.md)).
- Re-ingestion is safe. Running `lh status` (or a future scheduler job) on the same JSONLs over and over produces the same database.
- Adding a new view = one new file in `monitoring/views/` and one registration in `dashboard.py`. No schema change, no migration. (This held for views. The schema itself later needed both — see *Evolution*.)
- The collector filters project and profile out of the JSONL via the same decoder as `session_export` (see [ADR-011](011-session-export-and-classification.md)), sharing the calibration used for the knowledge directory.
- The schema is deliberately flat. Future features (per-tool usage breakdown, per-hook timing) will either add columns or introduce a second table, not restructure this one.

## Evolution

The decision this ADR records — SQLite, populated from session JSONLs, queried by view
modules — still holds. The schema block above does not: it describes the 2026-04-13 state
and is kept as the record of what was decided, not as documentation of what exists. Read
`src/lazy_harness/monitoring/db.py` for the current DDL.

Tables now created by `MetricsDB._ensure_schema`:

| Table | Purpose | Introduced by |
|---|---|---|
| `session_stats` | Per-session, per-model token and cost rows. The original table. | this ADR |
| `ingest_meta` | `mtime_ns` per session, so re-ingest skips untouched transcripts. | `lh metrics ingest` pipeline (#1) |
| `sink_outbox` | Durable queue of metric events pending delivery to a remote sink, with attempt count, backoff and lease. | metrics sink plugin slice (#8) |
| `loop_events` | Compound-loop events keyed by session and timestamp, written by `knowledge/compound_loop.py`. | loop instrumentation (#160) |
| `session_attribution` | `workload` and `host`, written by `lh exec` before the agent starts and joined at ingest. | [ADR-037](037-metric-event-v2-host-and-workload.md) (#223) |

`session_stats` also gained five columns beyond the ten above — `user_id`, `tenant_id`,
`event_id`, `host`, `workload` — added to existing databases by
`_migrate_identity_columns()` rather than by a rebuild. `event_id` is backfilled
deterministically from `(profile, session, model)` so the remote sink has a stable
idempotency key; `host` and `workload` are deliberately not backfilled, because nothing
on disk can say which machine wrote a historical row.

The last consequence listed above anticipated the shape of this growth: new features
would add columns or a table rather than restructure. That is what happened. What it did
not anticipate is that an embedded schema block goes stale silently — hence this section
and the pointer to the module.
