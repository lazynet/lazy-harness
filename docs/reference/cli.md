# CLI reference

For canonical flag lists, run `lh <command> --help` — this page is context, not a man page. Sections below follow the order of `lh --help`.

## `lh deploy`

Deploys profiles, hooks, skills, and MCP server entries from your config to the agent's config directories. Run it after editing `config.toml`, after adding a new profile, after installing/uninstalling an MCP-backed memory tool (QMD, Engram), or after pulling repo changes that touch profile contents.

The MCP wiring step ([ADR-024](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/024-mcp-server-orchestration.md)) probes each detected tool and writes/refreshes the `mcpServers` block inside every profile's `settings.json` next to the existing `hooks` block. Tools that are not installed get no entry; uninstalled tools have their entry removed on the next deploy.

It is idempotent: re-running on a clean tree is a no-op.

```bash
lh deploy
```

## `lh doctor`

Checks environment health and reports the status of optional features. Use it as the first thing after install and any time something feels off. `doctor` is read-only — it never mutates anything.

The output has two parts:

- **Environment checks** — Python version, agent binary present, config readable, profile dirs writable, `direnv` detected.
- **Features section** ([ADR-025](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/025-doctor-features-section.md)) — one row per memory-stack tool (`qmd`, `engram`, `graphify`) with state (`active`, `dormant`, `missing`), installed version vs pinned version, and a one-line hint when something needs attention. Tools that need an explicit enable in `config.toml` (e.g. `[memory.engram].enabled = true`) show as `dormant` until the flag flips. The `engram-persist` row reports loop health (`ok` / `warn` / `fail` / `missing`) classified from `~/.claude/logs/engram_persist_metrics.jsonl` against three thresholds: last-run age (warn ≥ 24 h, fail ≥ 7 d), recent failure rate (warn > 0%, fail > 10%), and cursor lag in bytes (fail ≥ 64 KiB).

A **Sink freshness** section reports, for every `[metrics]` sink `plan_sinks()` currently resolves as active (everything except `sqlite_local`, which is the local store itself, not a delivery pipeline), how long it has been since anything was last enqueued in `sink_outbox` — `ok` / `warn` (≥ 24 h) / `fail` (≥ 7 d) / `missing` (no history yet, not the same as stale). This catches a sink that quietly stopped moving data — e.g. an environment variable that resolved when the config was written but is unset wherever the scheduled ingest job actually runs — instead of doctor passing because the sink is merely *configured*. The same section reports a second, independent signal: how many rows are still undelivered in `sink_outbox` and how many times the drain has failed on the worst of them — `warn` at 3 failed attempts, `fail` at 6. Enqueue age cannot see a broken endpoint, because a sink that refuses every request keeps accepting enqueues just fine; and the two thresholds are attempt counts rather than durations because a failed row is returned to the queue with a longer backoff and no attempt ceiling, so age alone never distinguishes a stalled pipeline from a machine nobody used. This line is printed only once the drain has actually failed: between an enqueue and the drain that follows it there is always an untried row, so a backlog on its own is not a fault. The section is omitted entirely when `[monitoring].enabled` is false or no remote sink is active, since neither case has anything to check.

```bash
lh doctor
```

## `lh config`

Interactive wizards that write a typed config block back into `~/.config/lazy-harness/config.toml` ([ADR-026](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/026-config-wizards.md)). The wizards are opt-in — invoked explicitly per feature, never run on upgrade.

`lh config <feature> --init` runs the wizard for one feature, prompts for the values it needs, deep-merges the result into your existing config (preserving comments and unrelated sections), and exits. Re-running over an already-configured section asks before overwriting.

Currently shipped wizards:

- **`lh config memory --init`** — writes `[memory.engram]`. Probes whether `engram` is on `PATH` first; when missing, prints the pinned version and the install hint, then asks whether to write the section anyway (so a config can be staged before the binary lands). Prompts for `enabled`, `git_sync` (commit per-repo memory chunks under `.engram/chunks/`), and `cloud` (opt-in cloud sync, off by default to preserve the local-first guarantee). The pinned version is stamped automatically.
- **`lh config knowledge --init`** — writes `[knowledge.structure]` for Graphify. Same probe-and-stage pattern as the memory wizard: prompts for `enabled`. Pinned Graphify version is stamped automatically.

`lh config migrate-knowledge` is not a wizard. It rewrites an old `[knowledge]` block — `path`, `sessions.subdir`, `learnings.subdir`, and `compound_loop.learnings_subdir` — into the store-root shape, and is what the loader's error message points you at when it refuses a stale config. `--root <path>` sets the new `[knowledge].root`; a root you already set is never overwritten, and `[compound_loop].lazymind_dir` is left alone because it points at a vault rather than at the store.

Both wizards stamp the pinned tool version into the resulting block so `lh doctor` can later flag drift between the install and the config.

```bash
lh config memory --init
lh config knowledge --init
lh config migrate-knowledge --root ~/repos/lazy-knowledge
```

## `lh exec`

Runs the agent non-interactively and writes one normalised JSON envelope to stdout. Where `lh run` execs the agent and disappears, `lh exec` stays alive to translate the agent's own output format into a provider-neutral result — so a caller can change agents without changing its invocation or its parsing.

The prompt is read from **stdin**, never from argv: argv is bounded by `ARG_MAX` (1 MiB on macOS) and a long prompt is not. Arguments after `--` are forwarded to the agent verbatim; unknown arguments *before* `--` are rejected rather than silently forwarded.

The agent's stderr passes through untouched. Nothing but the envelope is ever written to stdout, including on failure.

```bash
echo "summarise this repo" | lh exec --tier fast --no-tools
echo "$PROMPT" | lh exec --profile work --allow-tools Read,Grep --timeout 300
lh exec --dry-run --tier deep          # plan only, no agent spawned, no stdin read
echo hi | lh exec -- --resume abc123   # everything after `--` goes to the agent
```

### Selecting a model

`--tier fast|balanced|deep` is the provider-neutral vocabulary; each adapter maps it to a concrete model (Claude Code: `haiku`, `sonnet`, `opus`). `--model <id>` passes an id straight through and is not validated. The two are mutually exclusive, and with neither the provider picks its own default.

### Tool policy

Three states, deliberately distinct:

| Flags | Meaning |
| --- | --- |
| *(neither)* | Leave the agent's own tool policy alone |
| `--no-tools` | Deny every tool the agent can be told to deny — pins the call to one turn |
| `--allow-tools Read,Grep` | Grant exactly these |

`--allow-tools ""` is refused: passing an empty allow-list to Claude Code is a no-op that silently leaves the default read tools enabled, so the ambiguity is rejected instead of inherited.

### Envelope

```json
{
  "schema": "lh.exec/v1",
  "dry_run": false,
  "success": true,
  "exit_code": 0,
  "output": "…the agent's reply…",
  "cost_usd": 0.0619,
  "duration_ms": 2100,
  "prompt_tokens": 30885,
  "output_tokens": 42,
  "cache_creation_tokens": 30876,
  "cache_read_tokens": 0,
  "num_turns": 1,
  "error": null,
  "harness": {
    "profile": "work",
    "profile_source": "root-match",
    "agent": "claude-code",
    "binary": "/…/claude",
    "config_dir": "/…/.claude-work",
    "lh_version": "0.47.0",
    "argv": ["/…/claude", "-p", "--output-format", "json"]
  },
  "raw": { "…": "the provider's own envelope, verbatim" }
}
```

Every numeric field is `null` when the provider did not report it — never `0`. A provider without a prompt cache reports `null` cache tokens, because "no cache exists" and "nothing was cached this call" are different facts and a `0` enters a cost report as the second one. `prompt_tokens` is the **sum** of the uncached, cache-creation and cache-read counts: Claude Code's own `input_tokens` covers only the uncached slice of the final turn and reads as single digits on a 100k-token prompt.

`harness.profile_source` is `explicit` (`--profile`), `root-match` (the cwd fell under a configured root) or `default-fallback` (nothing matched, so the default profile was a guess). A caller recording which provider it was billed for should record this alongside the cost.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The agent ran and succeeded |
| *(agent's own)* | The agent ran and exited non-zero; mirrored verbatim |
| `2` | Usage error — conflicting or unknown flags, unknown tier |
| `70` | Harness failure before the agent ran: bad config, unknown profile, agent cannot run headless, binary not found, empty prompt |
| `124` | The agent exceeded `--timeout` and its process group was killed |

`--timeout` (default 600s, `0` disables) is owned by `lh exec`, which kills the agent's whole **process group** — killing only the direct child leaves grandchildren such as MCP servers running and billable. A caller wrapping `lh exec` in its own timeout should set that backstop above this one.

## `lh hook`

Invokes a single built-in hook by name. This is what `settings.json` entries actually call — the agent runs `lh hook <name>` and the command imports the matching builtin module and calls its `main()`.

You should rarely run this by hand. It is documented so the entries in `profiles/<name>/settings.json` make sense.

```bash
lh hook compound-loop
```

## `lh hooks`

Manages hooks (note the plural — distinct from `lh hook`).

`lh hooks list` enumerates every hook the harness knows about: built-ins shipped with `lazy-harness`, plus user hooks declared in `[hooks.<event>]` sections of `config.toml`.

`lh hooks run <event>` fires every hook registered for an event. This is the debugging entry point — use it to reproduce a hook misfire without bouncing through the agent.

```bash
lh hooks list
lh hooks run SessionStart
```

## `lh init`

Initializes lazy-harness for a fresh machine: writes `~/.config/lazy-harness/config.toml`, sets up data and cache dirs, and primes a default profile. Refuses to run on a machine that already has Claude Code state — that is what `lh migrate` is for.

Pass `--force` to wipe and reinitialize, backing up the existing config first.

```bash
lh init
lh init --force
```

## `lh knowledge`

Manages the knowledge store and its QMD index.

`lh knowledge init` creates the store, writes its `knowledge.toml` marker, and creates the subdirectories the marker declares. `--root <path>` overrides where; without it the store root is resolved from `$LAZY_KNOWLEDGE_ROOT`, then `[knowledge].root` in `config.toml`, then the built-in default. Re-running it is safe: an existing marker is never overwritten.

`lh knowledge path` prints an absolute path inside the store. `--kind root` (the default), `--kind sessions`, or `--kind learnings`; the two subdirectory names come from the marker, never from configuration. It exits non-zero when the store has no readable marker, which makes it usable as a guard in shell scripts.

`lh knowledge push` runs one commit / `pull --rebase` / push cycle over the store and appends the outcome to `knowledge-push.log`. It is the command the scheduler job runs, and it is also safe to run by hand before switching machines. A concurrent cycle is skipped silently (exit 0); a rebase conflict aborts the rebase and exits 1 without ever auto-resolving. Producers — the `session-export` hook and the compound-loop worker — never invoke git themselves, so a dead remote or missing network delays a push but cannot lose a write.

`lh knowledge status` shows where the store lives, how many sessions are inside, and whether QMD is reachable.

`lh knowledge sync` rebuilds the BM25 lexical index. `lh knowledge embed` runs vector embedding for semantic search. Both accept `--collection <name>` to scope to one collection instead of all of them.

`lh knowledge context-gen` regenerates the auto-updated stats blocks inside QMD collection contexts (the `<!-- auto -->` markers). `--dry-run` shows changes without writing.

`lh knowledge handoff-now` forces a compound-loop evaluation for the current session, bypassing the debounce and growth gates the Stop hook applies. Same semantics as the `SessionEnd` hook ([ADR-019](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/019-handoff-session-end-freshness.md)); use it manually before `/compact`, before closing a terminal without `/exit`, or on Claude Code builds that predate the `SessionEnd` event.

`lh knowledge export-session <session-file>` is the escape hatch for sessions the `Stop` / `session-export` hook skipped — for example, a real session the non-interactive heuristic mis-classified. `--force` bypasses the interactive-session filter and the unchanged-file guard.

`lh knowledge graph add|list|update` manages the repos whose code graph is kept fresh.

Nothing rebuilds a code graph on its own in a worktree-first workflow: graphify's `post-commit` hook exits early when the git dir differs from the common dir, so a commit made inside a worktree never triggers a rebuild — and a squash merge landing on the remote produces no local commit at all. `graph update` is the scheduled sweep that closes that gap. Point a `[scheduler.jobs.*]` entry at it.

`add` registers a repo after checking it really is one, and is idempotent. It updates `repos` under `[knowledge.structure]` through the normal config writer, which preserves comments, formatting, and every key this version does not model. `update` walks every registered repo, skips ones that have gone missing, keeps going past a repo that fails, and exits non-zero if any did. Outcomes append to `graphify-update.log`.

```bash
lh knowledge init
lh knowledge path --kind learnings
lh knowledge push
lh knowledge status
lh knowledge sync --collection my-project
lh knowledge embed
lh knowledge context-gen --dry-run
lh knowledge handoff-now
lh knowledge export-session ~/.claude/projects/-Users-me-repo/abc123.jsonl --force
lh knowledge graph add ~/repos/my-project
lh knowledge graph list
lh knowledge graph update
```

## `lh memory`

Diagnostic commands for the memory stack. Read-only inspection plus a propose-only consolidator — none of these write to `MEMORY.md` directly. Pair them with `lh status memory` for per-project counts.

### `lh memory consolidate`

Proposes additions to `MEMORY.md` distilled from the most recent decisions and failures in the per-project memory dir. The command is read-only: it prints a proposal to stdout (typically a few bullet points fit for the curated semantic layer) and never edits `MEMORY.md` itself. Pair it with the warning emitted by `pre-tool-use-memory-size` when the file is near the 200-line or 12KB ceiling ([ADR-030](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/030-memory-stack-glue-layer.md) G2).

Flags:

- `--memory-dir <path>` — directory to read from. Defaults to `<cwd>/memory`.
- `--last <n>` — tail this many entries from each JSONL. Default `50`.
- `--model <id>` — headless model used to draft the proposal. Default `claude-haiku-4-5-20251001`.
- `--timeout <seconds>` — Claude invocation timeout. Default `120`.

```bash
lh memory consolidate
lh memory consolidate --memory-dir ~/.claude/projects/-Users-me-repo/memory --last 100
```

### `lh memory legacy-check`

Reports per-project memory still sitting in a profile's `projects/` tree rather than in the knowledge store, and classifies each one:

- **orphaned** — the store holds no copy, so nothing reads this memory any more. Move it with `lh memory migrate`.
- **superseded** — the store already holds a copy; the leftover is safe to delete.
- **unkeyable** — the checkout it was named after is gone, or has no git remote to key on, so there is nowhere to move it.

```bash
lh memory legacy-check
```

### `lh memory proposals`

Lifecycle for the `claude-md.proposal.md` entries the compound loop appends (see [Memory: the compound loop](../how/memory-compound.md)). All three subcommands take `--memory-dir <path>`; by default the per-project memory dir is resolved from the agent runtime dir and the repository the working directory belongs to. Inside a linked git worktree the key comes from the main checkout, so proposals stay on the file the loop writes to instead of following each worktree.

- `lh memory proposals list` — numbered table of pending proposals (index, date, rule excerpt).
- `lh memory proposals accept <N>` — removes entry N from the pending file, archives it to `claude-md.accepted.md` with the acceptance date, and prints the full rule. It never edits `MEMORY.md` or `CLAUDE.md` itself — pasting the rule is the human's call.
- `lh memory proposals reject <N> --reason "<text>"` — removes entry N and records it in `claude-md.rejected.md` with the date and reason. That file is an immunity registry: the grading prompt includes the last 20 rejected rules with an instruction not to re-propose equivalents.

```bash
lh memory proposals list
lh memory proposals accept 1
lh memory proposals reject 2 --reason "too strict for this repo"
```

## `lh migrate`

Takes an existing Claude Code install and converts it into a lazy-harness setup: backs up state, detects profiles and LaunchAgents, rewrites paths, writes a new `config.toml`.

`--dry-run` analyzes and prints the plan without touching anything; the real migration requires a recent dry-run before it will execute. `--rollback` undoes the last migration using its rollback log.

```bash
lh migrate --dry-run
lh migrate
lh migrate --rollback
```

## `lh metrics`

Manages the metrics pipeline: session-rollup ingestion plus per-event sink fanout.

### `lh metrics ingest`

Walks every profile's `<config_dir>/projects/**/*.jsonl`, aggregates token usage per `(session, model)`, prices it with `[monitoring.pricing]` overrides (falling back to `DEFAULT_PRICING`), and UPSERTs into `session_stats`. The pipeline is safe to run repeatedly — it tracks each session's file mtime in a separate `ingest_meta` table and skips files that haven't changed since the previous run. Re-ingesting the same file is idempotent: totals are re-computed from the full (append-only) JSONL and overwrite prior rows, so token counts never accumulate double.

After the SQL upsert, every active sink declared in `[metrics].sinks` writes the resulting events. With the default `["sqlite_local"]`, that is a no-op write into the same DB. With `http_remote` added, ingest also opportunistically drains the outbox in the same process, so a single `lh metrics ingest` tick covers both write and ship.

`--dry-run` parses everything but writes to an in-memory DB so you can preview the scan without touching the real one. `-v/--verbose` surfaces any per-file errors the walk hit.

Pair with `lh scheduler` to keep the DB fresh — add a job under `[scheduler.jobs.metrics-ingest]` with a cron expression (e.g. `*/15 * * * *`) calling `lh metrics ingest`.

```bash
lh metrics ingest --dry-run
lh metrics ingest
```

### `lh metrics drain`

Force-drains the outbox for every configured remote sink without re-running ingest. Useful after a backend outage to flush the backlog without paying the cost of re-scanning every JSONL. Honors the same per-row exponential backoff and 60-second lease as the opportunistic drain inside `ingest`.

```bash
lh metrics drain
```

Output is one summary line: `drain complete: <sent> sent, <failed> failed`.

### `lh metrics status`

Prints the local database summary (session count, accumulated cost, path), then per-sink outbox counters (`pending`, `sending`, `sent`) for every non-`sqlite_local` sink. Use it to spot a stuck `http_remote` without `sqlite3`-ing the DB.

```bash
lh metrics status
# sqlite_local  8431 sessions  $412.87  ~/.config/lazy-harness/metrics.db
# http_remote  pending: 12  sending: 0  sent: 8431
```

When `sqlite_local` is the only configured sink — the default — the command reports that no remote sinks are configured instead of printing nothing.

Mechanics — sinks, outbox, drain policy, idempotency: [how the metrics ingest pipeline works](../how/metrics-ingest.md#the-sink-layer).

### `lh metrics loops`

Reports counts from the `loop_events` table, grouped by `kind` (e.g. `session_closed`, `nontrivial_prompt`, `goal_declared`, `goal_absent`), followed by the declared-goal rate. This is the phase-0 sensor data for the feedback-loop feature — see [how the hooks complement each other](../how/hooks.md#how-the-hooks-complement-each-other) for what writes to this table and when.

`--days N` restricts the count to events from the last N days; omit it to count everything. `--db PATH` overrides the DB path outright, bypassing config resolution entirely — useful for inspecting a specific file. Without `--db`, the command resolves the same way every other `lh metrics`/`lh status` command does: `[monitoring] db` from `config.toml` if set, otherwise `data_dir()/metrics.db`.

The declared rate is `goal_declared / (goal_declared + goal_absent)`, rendered as a percentage with the raw counts alongside it; `considered == 0` prints `0%` rather than dividing by zero. Both event kinds come from the compound-loop worker grading a session, one verdict per session it grades — a `UserPromptSubmit` hook fires before any assistant text exists and cannot itself judge whether a criterion was declared. `nontrivial_prompt` is the separate, per-prompt sensor recorded by `user_prompt_goal.py`.

```bash
lh metrics loops
lh metrics loops --days 14
lh metrics loops --db ~/.config/lazy-harness/metrics.db
# goal_absent          6
# goal_declared        3
# nontrivial_prompt    9
# session_closed       12
#
# declared rate: 33% (3/9)
```

## `lh profile`

Manages agent profiles.

`lh profile list` prints a table of every configured profile — name, config dir, roots, whether the config dir actually exists on disk.

`lh profile add <name> --config-dir <path> [--roots a,b,c]` registers a new profile in `config.toml`. `lh profile remove <name>` does the inverse.

`lh profile envrc` walks every profile's roots and writes a managed `.envrc` block exporting the agent's config-dir env var (e.g. `CLAUDE_CONFIG_DIR`). With direnv installed, plain `claude` invocations inside a root then auto-pick the right profile. User content outside the managed block is preserved. `--dry-run` shows what it would write.

`lh profile move --from <a> --to <b>` relocates per-project conversation history (`<config_dir>/projects/<encoded-cwd>/`) between profiles without losing JSONL history. Useful when reclassifying a project from one profile to another. Supports `--projects a,b,c`, `--all`, `--overwrite`, and `--yes`.

```bash
lh profile list
lh profile add work --config-dir ~/.claude-work --roots ~/repos/work
lh profile envrc
lh profile move --from personal --to work --projects my-repo --yes
```

## `lh run`

Resolves the right profile for the current directory (or `--profile <name>`), sets the agent's config-dir env var, and execs the agent binary with all remaining args. This is the canonical way to launch the agent through the harness.

`--list` prints profiles and exits. `--dry-run` prints the resolved exec invocation without running.

If no configured root matches the current directory, the default profile is used and a warning naming the directory and the profile is written to **stderr** — never stdout, which belongs to the agent once `lh run` execs it. The warning is unconditional rather than interactive-only: a scheduled caller has no terminal and is the one most likely to be launching from an unrouted directory. It is suppressed when no profile declares a root at all, since routing by directory is then not in use and the default is the configured design rather than a guess.

```bash
lh run                    # launch agent for current cwd's profile
lh run --profile work
lh run --dry-run -- --resume
```

## `lh scheduler`

Manages scheduled jobs declared in `[scheduler.jobs.<name>]`. The backend is auto-detected (launchd on macOS, systemd on Linux with `systemctl`, cron otherwise) or pinned via `[scheduler] backend`. All three install, uninstall and report state.

`install` is all-or-nothing: every job's schedule is translated before anything is written, so an expression the backend cannot express aborts the run and leaves the existing set untouched. On systemd, `install` also checks whether lingering is enabled and says so if it is not — user timers stop when your last session ends, and `systemctl --user enable --now` reports success either way.

`lh scheduler install` writes the platform-native unit files for every declared job, `lh scheduler uninstall` removes them, and `lh scheduler status` shows the active backend and per-job state. All three work on every supported platform.

```bash
lh scheduler status
lh scheduler install
lh scheduler uninstall
```

## `lh selftest`

Validates the lazy-harness install end-to-end: config parses, profiles deploy, hooks fire, scheduler reachable. Use it after upgrades, after editing config, or as a smoke test in scripts.

The `loop-events` group goes further than the others: it builds a throwaway git repository, runs the loop-event hook scripts the installed package ships, and reads back the rows they wrote. That catches attribution bugs — a session recorded against an artifact subdirectory instead of its repository, or a row that cannot name its profile — which unit tests cannot see, because they import the hooks rather than running them as the agent does.

The `scheduler` group's `units-stale` check compares each installed job against what the current version would write, and warns naming the jobs that differ. A plist, a timer unit and a crontab block are written once and read for months, so they outlive the code that produced them: a job can be installed, loaded and counted while carrying an environment or a schedule this version no longer generates. Re-run `lh scheduler install` to refresh them.

`--json` switches to machine-readable output. `--fix` attempts to repair fixable issues in place.

```bash
lh selftest
lh selftest --json
lh selftest --fix
```

## `lh status`

Monitoring dashboard. With no subcommand, prints the overview panel. There are ten subcommand views.

- `overview` — at-a-glance summary panel.
- `sessions` — daily breakdown of sessions, tokens, cost. `--period today|week|month|all`.
- `tokens` — token / cost breakdown across any combination of dimensions. See below.
- `costs` — legacy cost view, kept for back-compat. `--period 7d|30d|month|all`.
- `projects` — per-project session counts and last activity.
- `profiles` — per-profile config, hooks count, MCPs, auth state.
- `hooks` — last fired hooks plus log health.
- `cron` — scheduled launchd jobs and their last runs.
- `queue` — compound-loop queue depth and recent worker activity.
- `memory` — per-project decisions / failures / learnings counts.

```bash
lh status
lh status sessions --period week
lh status tokens --by model --period month
```

### `lh status tokens`

| Flag | Values | Default | Notes |
| --- | --- | --- | --- |
| `--by` | `profile` `project` `model` `day` `week` `month` | `project` + `model` | Repeatable. Flag order is column order. |
| `--period` | `today` `week` `month` `all`, `<N>d`, `YYYY-MM`, `YYYY-MM-DD` | `month` | `week` and `<N>d` are rolling windows ending today. |
| `--profile` | any string | — | Case-insensitive substring filter. |
| `--model` | any string | — | Case-insensitive substring filter. |
| `--project` | any string | — | Case-insensitive substring filter. |
| `--json` | flag | off | Emits the aggregation instead of the table. |

Each `--by` adds a grouping column, so `--by month --by profile` gives one row
per month per profile. With two or more dimensions the table also carries a
subtotal row per value of the first dimension. Filters narrow the rows without
adding a column: `--profile work --by month` is one row per month, work only.

`--period` accepts more than the four keywords — `30d` for a rolling month,
`2026-04` for one calendar month, `2026-04-15` for a single day.

```bash
lh status tokens --by profile --period all
lh status tokens --by month --by profile
lh status tokens --by model --profile work --period 30d
lh status tokens --by day --period 2026-04 --json
```

Full walkthrough with worked examples: [Cost reporting](../how/cost-reporting.md).

## `lh statusline`

Reads a Claude Code status payload on stdin and prints the formatted status line. Wired into a profile via `settings.json`:

```json
"statusLine": { "type": "command", "command": "lh statusline" }
```

You generally do not invoke this by hand — Claude Code calls it on every status refresh.
