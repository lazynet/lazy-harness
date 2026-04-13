# CLI reference

For canonical flag lists, run `lh <command> --help` — this page is context, not a man page. Sections below follow the order of `lh --help`.

## `lh deploy`

Deploys profiles, hooks, and skills from your config to the agent's config directories. Run it after editing `config.toml`, after adding a new profile, or after pulling repo changes that touch profile contents.

It is idempotent: re-running it on a clean tree should be a no-op.

```bash
lh deploy
```

## `lh doctor`

Checks environment health: Python version, agent binary present, config readable, profile dirs writable, optional dependencies (QMD, direnv) detected. Use it as the first thing after install and any time something feels off.

`doctor` is read-only. It never mutates anything.

```bash
lh doctor
```

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

Manages the knowledge directory and its QMD index.

`lh knowledge status` shows where the knowledge dir lives, how many sessions and learnings are inside, and whether QMD is reachable.

`lh knowledge sync` rebuilds the BM25 lexical index. `lh knowledge embed` runs vector embedding for semantic search. Both accept `--collection <name>` to scope to one collection instead of all of them.

`lh knowledge context-gen` regenerates the auto-updated stats blocks inside QMD collection contexts (the `<!-- auto -->` markers). `--dry-run` shows changes without writing.

```bash
lh knowledge status
lh knowledge sync --collection my-project
lh knowledge embed
lh knowledge context-gen --dry-run
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

Ingests agent session JSONLs into the monitoring SQLite DB so `lh status` can show real sessions/tokens/cost numbers.

`lh metrics ingest` walks every profile's `<config_dir>/projects/**/*.jsonl`, aggregates token usage per `(session, model)`, prices it with `[monitoring.pricing]` overrides (falling back to `DEFAULT_PRICING`), and UPSERTs into `session_stats`. The pipeline is safe to run repeatedly — it tracks each session's file mtime in a separate `ingest_meta` table and skips files that haven't changed since the previous run. Re-ingesting the same file is idempotent: totals are re-computed from the full (append-only) JSONL and overwrite prior rows, so token counts never accumulate double.

`--dry-run` parses everything but writes to an in-memory DB so you can preview the scan without touching the real one. `-v/--verbose` surfaces any per-file errors the walk hit.

Pair with `lh scheduler` to keep the DB fresh — add a job under `[scheduler.jobs.metrics-ingest]` with a cron expression (e.g. `*/15 * * * *`) calling `lh metrics ingest`.

```bash
lh metrics ingest --dry-run
lh metrics ingest
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
lh profile move --from lazy --to flex --projects my-repo --yes
```

## `lh run`

Resolves the right profile for the current directory (or `--profile <name>`), sets the agent's config-dir env var, and execs the agent binary with all remaining args. This is the canonical way to launch the agent through the harness.

`--list` prints profiles and exits. `--dry-run` prints the resolved exec invocation without running.

```bash
lh run                    # launch agent for current cwd's profile
lh run --profile work
lh run --dry-run -- --resume
```

## `lh scheduler`

Manages scheduled jobs declared in `[scheduler.jobs.<name>]`. The backend is auto-detected (launchd on macOS, systemd on Linux, cron as fallback) or pinned via `[scheduler] backend`.

`lh scheduler install` writes the platform-native unit files for every declared job. `lh scheduler uninstall` removes them. `lh scheduler status` shows the active backend and per-job state.

```bash
lh scheduler status
lh scheduler install
lh scheduler uninstall
```

## `lh selftest`

Validates the lazy-harness install end-to-end: config parses, profiles deploy, hooks fire, scheduler reachable. Use it after upgrades, after editing config, or as a smoke test in scripts.

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
- `tokens` — token / cost breakdown grouped by `--by project|model|profile`. `--period today|week|month|all`.
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

## `lh statusline`

Reads a Claude Code status payload on stdin and prints the formatted status line. Wired into a profile via `settings.json`:

```json
"statusLine": { "type": "command", "command": "lh statusline" }
```

You generally do not invoke this by hand — Claude Code calls it on every status refresh.
