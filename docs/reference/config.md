# Config reference

`~/.config/lazy-harness/config.toml` is the single source of truth for a lazy-harness install. Every command — `lh run`, `lh deploy`, `lh status`, `lh scheduler`, the hooks — reads it on each invocation. There is no daemon, no in-memory cache: edit, save, run again.

The file location follows XDG: `$LH_CONFIG_DIR/config.toml`, then `$XDG_CONFIG_HOME/lazy-harness/config.toml`, then the platform default (`~/.config/lazy-harness/config.toml` on macOS/Linux, `%APPDATA%\lazy-harness\config.toml` on Windows).

## Minimal example

The smallest config that loads cleanly:

```toml
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "personal"

[profiles.personal]
config_dir = "~/.claude-personal"
roots = ["~"]
```

`[harness].version` is the only field the parser hard-requires. Everything else has a default.

## Fuller example

A more realistic shape with knowledge, monitoring, scheduler jobs, hooks, and the compound loop:

```toml
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "lazy"

[profiles.lazy]
config_dir = "~/.claude-lazy"
roots = ["~/repos/lazy"]
lazynorth_doc = "LazyNorth-lazy.md"

[profiles.flex]
config_dir = "~/.claude-flex"
roots = ["~/repos/flex"]

[knowledge]
path = "~/vault/knowledge"

[knowledge.sessions]
enabled = true
subdir = "sessions"

[knowledge.learnings]
enabled = true
subdir = "learnings"

[knowledge.search]
engine = "qmd"

[monitoring]
enabled = true
db = "~/.local/share/lazy-harness/monitoring.db"

[monitoring.pricing.claude-sonnet-4-5]
input = 3.0
output = 15.0

[scheduler]
backend = "auto"

[scheduler.jobs.weekly-review]
schedule = "0 9 * * 1"
command = "lh knowledge sync"

[hooks.session_start]
scripts = ["context-inject"]

[hooks.session_stop]
scripts = ["compound-loop"]

[compound_loop]
enabled = true
model = "claude-haiku-4-5-20251001"
min_messages = 4
min_user_chars = 200

[lazynorth]
enabled = true
path = "~/vault/LazyNorth"

[context_inject]
enabled = true
max_body_chars = 3000
last_session_enabled = true
proposals_summary = true
repo_map_scope = "~/repos/work"
```

## `[harness]`

| Field     | Type   | Default | Required | Description                                                |
| --------- | ------ | ------- | -------- | ---------------------------------------------------------- |
| `version` | string | —       | yes      | Schema version. Currently `"1"`. Parsing fails without it. |

## `[agent]`

| Field  | Type   | Default         | Required | Description                                                                                                         |
| ------ | ------ | --------------- | -------- | ------------------------------------------------------------------------------------------------------------------- |
| `type` | string | `"claude-code"` | no       | Agent adapter to load. Determines the config-dir env var (e.g. `CLAUDE_CONFIG_DIR`) and binary name `lh run` execs. |

## `[profiles]` and `[profiles.<name>]`

The `[profiles]` table holds one bare key (`default`) plus one sub-table per profile. The parser walks every key in `[profiles]`, treats `default` as the default profile name, and treats every other key whose value is a table as a profile entry.

| Field     | Type   | Default      | Required | Description                                  |
| --------- | ------ | ------------ | -------- | -------------------------------------------- |
| `default` | string | `"personal"` | no       | Name of the profile used when none resolves. |

Each `[profiles.<name>]` sub-table:

| Field           | Type            | Default | Required | Description                                                                           |
| --------------- | --------------- | ------- | -------- | ------------------------------------------------------------------------------------- |
| `config_dir`    | string (path)   | `""`    | yes\*    | Agent config directory for this profile. `~` is expanded.                             |
| `roots`         | list of strings | `[]`    | no       | Filesystem roots that resolve to this profile (used by `lh run` and `profile envrc`). |
| `lazynorth_doc` | string          | `""`    | no       | Per-profile LazyNorth doc filename. Overrides `[lazynorth].universal_doc`.            |

\* `config_dir` has no parser-level requirement, but everything downstream (`lh run`, `lh deploy`, `lh profile envrc`) is meaningless without it.

## `[knowledge]` and sub-tables

| Field  | Type          | Default | Required | Description                                                                                                          |
| ------ | ------------- | ------- | -------- | -------------------------------------------------------------------------------------------------------------------- |
| `root` | string (path) | `""`    | no       | Root of the knowledge store repository. Empty falls back to `$LAZY_KNOWLEDGE_ROOT`, then to the built-in default. |

The store's *layout* is not configured here. A `knowledge.toml` marker at the
store root declares its subdirectory names, and every consumer reads them from
there. See [The knowledge store](../how/knowledge-pipeline.md).

`[knowledge.sessions]`:

| Field     | Type   | Default      | Required | Description                                           |
| --------- | ------ | ------------ | -------- | ----------------------------------------------------- |
| `enabled` | bool   | `false`      | no       | Whether session export writes into the knowledge store. |

`[knowledge.learnings]`:

| Field     | Type   | Default       | Required | Description                                             |
| --------- | ------ | ------------- | -------- | ------------------------------------------------------- |
| `enabled` | bool   | `false`       | no       | Whether the compound loop persists distilled learnings. |

`[knowledge.search]`:

| Field    | Type   | Default | Required | Description                                       |
| -------- | ------ | ------- | -------- | ------------------------------------------------- |
| `engine` | string | `"qmd"` | no       | Search backend. Only `qmd` is implemented today. |

`[knowledge.structure]` — code-structure layer ([Graphify](https://github.com/safishamsi/graphify)):

| Field                    | Type   | Default      | Required | Description                                                                                                                              |
| ------------------------ | ------ | ------------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `engine`                 | string | `"graphify"` | no       | Structure backend. Only `graphify` is implemented today.                                                                                 |
| `enabled`                | bool   | `false`      | no       | Whether `lh deploy` wires the Graphify MCP entry into each profile's `settings.json`.                                                    |
| `version`                | string | `"0.9.41"`    | no       | Pinned Graphify version. `lh doctor` flags drift between this and the installed binary so upgrades are explicit. See [ADR-023](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/023-graphify-code-structure.md). |

`[[knowledge.classify_rules]]` (array of tables — see [ADR-028](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/028-classify-rules-configurable.md)):

| Field          | Type   | Default | Required | Description                                                                                  |
| -------------- | ------ | ------- | -------- | -------------------------------------------------------------------------------------------- |
| `pattern`      | string | —       | yes      | Case-insensitive substring matched against the session `cwd`.                                |
| `profile`      | string | —       | yes      | Value written to the export's `profile:` frontmatter when this rule matches.                 |
| `session_type` | string | —       | yes      | Value written to the export's `session_type:` frontmatter when this rule matches.            |

Rules are evaluated in order; the first match wins. Omitting the section uses a built-in default list (matching `lazymind`/`obsidian` → `vault`, `/repos/lazy/` → `personal`, `/repos/flex/` → `work`). To opt out of all defaults, declare `classify_rules = []` directly under `[knowledge]`.

```toml
[[knowledge.classify_rules]]
pattern = "/srv/clients/acme/"
profile = "client"
session_type = "acme"

[[knowledge.classify_rules]]
pattern = "/opt/research/"
profile = "research"
session_type = "experiment"
```

## `[memory]`

The `[memory]` block configures **agent-side** memory backends — tools the agent calls during a session. Today this is just Engram. It is independent of `[knowledge]` (file-based knowledge tree) and `[monitoring]` (SQLite metrics store).

`[memory.engram]` — raw episodic memory store ([Engram](https://github.com/Gentleman-Programming/engram)):

| Field      | Type   | Default      | Required | Description                                                                                                                                     |
| ---------- | ------ | ------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `enabled`  | bool   | `false`      | no       | When true, `lh deploy` wires the Engram MCP server into each profile's `settings.json` and the `engram-persist` Stop hook becomes meaningful.   |
| `git_sync` | bool   | `true`       | no       | Whether Engram persists per-repo memory chunks under a versioned `.engram/chunks/` directory (recommended; keeps knowledge with the code).      |
| `cloud`    | bool   | `false`      | no       | Opt-in cloud sync. Off by default — enabling it breaks the framework's local-first guarantee, so flip it deliberately.                          |
| `version`  | string | `"1.20.0"`   | no       | Pinned Engram version. `lh doctor` flags drift. See [ADR-022](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/022-engram-episodic-memory.md) and [ADR-029](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/029-engram-persist-deterministic-mirror.md). |

The interactive `lh config memory --init` wizard (see [ADR-026](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/026-config-wizards.md)) writes this block for you and merges it into an existing config preserving comments and unrelated sections.

## `[monitoring]`

The `[monitoring]` block controls the **session-rollup** SQLite store written by `lh metrics ingest`. It is independent of `[metrics]` (per-event sink fanout, see below) — they coexist.

| Field     | Type          | Default | Required | Description                                                                                                                    |
| --------- | ------------- | ------- | -------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `enabled` | bool          | `false` | no       | Whether the monitoring pipeline writes to SQLite.                                                                              |
| `db`      | string (path) | `""`    | no       | Path to the monitoring DB. Empty falls back to the data dir default.                                                           |
| `pricing` | table         | `{}`    | no       | Per-model pricing for cost rollups, e.g. `[monitoring.pricing.<model>]` with `input` / `output` / `cache_read` / `cache_create` (5-minute TTL write) / `cache_create_1h` (1-hour TTL write) USD-per-million-tokens floats. |

## `[metrics]`

The `[metrics]` block configures **per-event** sink fanout: where each `MetricEvent` is written when the framework records one. Distinct from `[monitoring]`, which controls session-level rollups.

The default — no `[metrics]` block at all — keeps everything local: only the built-in `sqlite_local` sink runs, and the framework does zero network I/O. Adding any other sink is opt-in.

| Field              | Type            | Default            | Required | Description                                                                                                                                                                                                                                              |
| ------------------ | --------------- | ------------------ | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sinks`            | list of strings | `["sqlite_local"]` | no       | Active sinks, in order. Built-ins: `sqlite_local`, `http_remote`. Any sink other than `sqlite_local` **requires** a corresponding `[metrics.sink_options.<name>]` block, otherwise the parser raises `ConfigError`. Unknown sinks are also a hard error. |
| `user_id`          | string          | `""`               | no       | Identity column stamped on every event. Empty falls back to `lazy_harness.core.identity.resolve_identity()` (env var → git config → hostname).                                                                                                            |
| `tenant_id`        | string          | `"local"`          | no       | Identity column stamped on every event.                                                                                                                                                                                                                  |
| `pending_ttl_days` | integer / null  | `null`             | no       | Outbox rows older than this are pruned. `null` keeps them forever (retried indefinitely under exponential backoff).                                                                                                                                       |

`[metrics.sink_options.<name>]` — per-sink options table. Required for every non-`sqlite_local` sink named in `sinks`; ignored for unknown names.

`http_remote` options:

| Field             | Type   | Default | Required | Description                                                                                                                |
| ----------------- | ------ | ------- | -------- | -------------------------------------------------------------------------------------------------------------------------- |
| `url`             | string | —       | one of   | HTTP(S) endpoint receiving `application/json` payloads. Mutually exclusive with `url_env`.                                 |
| `url_env`         | string | —       | one of   | Name of an environment variable holding the endpoint, resolved at run time. Unset or empty **deactivates the sink** — not an error; the run continues on `sqlite_local` and `lh doctor` reports it as configured-but-inactive. Mutually exclusive with `url`. |
| `timeout_seconds` | float  | `5.0`   | no       | Per-request HTTP timeout.                                                                                                  |
| `batch_size`      | int    | `50`    | no       | Number of outbox rows claimed per drain pass. Lease (60 s) is held while the batch is in flight to avoid double-sending. |

```toml
[metrics]
sinks = ["sqlite_local", "http_remote"]
tenant_id = "acme"
pending_ttl_days = 30

[metrics.sink_options.http_remote]
url = "https://metrics.example.com/v1/ingest"
timeout_seconds = 5.0
batch_size = 50
```

Naming the variable instead of the endpoint keeps the value off disk and makes
the remote sink opt-in per machine — a checkout that never sets the variable
runs local-only with no config edit:

```toml
[metrics]
sinks = ["sqlite_local", "http_remote"]

[metrics.sink_options.http_remote]
url_env = "LH_METRICS_URL"
```

Setting both `url` and `url_env` on the same sink is a `ConfigError`: preferring
one silently would make a typo in the other look like it worked. Setting neither
is an error too, raised when the sinks are built.

A scheduler job (launchd/systemd) does not inherit an interactive shell's
exported environment, so `url_env` can resolve fine in a terminal and still
come back empty when the identical config runs on a timer. When the variable
is unset or empty, `url_env` resolution falls back to reading it from
`<lh config dir>/secrets/metrics.env` — `KEY=value` lines, `#` comments and
blank lines allowed, same format as per-profile secrets files. The file must
be owner-only (`chmod 600`); one that grants any group or other permission is
refused outright and treated the same as a missing file. The environment
always wins: when `url_env` is set in the process environment, the file is
never read.

End-to-end mechanics — outbox, drain, backoff, idempotency: [how the metrics ingest pipeline works](../how/metrics-ingest.md#the-sink-layer).

## `[scheduler]` and `[scheduler.jobs.<name>]`

| Field      | Type   | Default  | Required | Description                                                                          |
| ---------- | ------ | -------- | -------- | ------------------------------------------------------------------------------------ |
| `backend`  | string | `"auto"` | no       | Scheduler backend. `auto` picks launchd (macOS), systemd (Linux with `systemctl`), or cron. All three install jobs. |
| `timezone` | string | unset    | no       | IANA zone the schedules are read in, e.g. `"America/Argentina/Buenos_Aires"`. Unset means the machine's own zone. |

`timezone` exists because a headless host usually runs `Etc/UTC` while the schedules are written for a human's day. Without it, a job declared `0 8 * * 1` fires at 08:00 UTC — the wrong hour anywhere else, with every status view reporting it as correct.

Only the systemd backend can express it, as a suffix on `OnCalendar=`. launchd reads `StartCalendarInterval` in local time and has no key to override it, so rather than accept the field and ignore it, **it refuses to install when the declared zone is not the one the machine currently observes**. That keeps a single config shared across a Mac and a Linux host honest.

Each `[scheduler.jobs.<name>]` sub-table:

| Field      | Type   | Default | Required | Description                                              |
| ---------- | ------ | ------- | -------- | -------------------------------------------------------- |
| `schedule` | string | —       | yes      | Cron expression, restricted to the subset below. Missing → `ConfigError`. |
| `command`  | string | —       | yes      | Shell command to run on each fire. Missing → `ConfigError`. |

The job's `name` is the TOML key — there is no `name` field inside the table.

### Supported schedule expressions

`schedule` is a five-field cron expression, but each backend only accepts what it can express exactly. An expression the backend cannot translate faithfully **aborts `lh scheduler install` and installs nothing** — no job is written, so the whole set stays as it was. The alternative, approximating, is what previously caused every non-daily job to be installed as hourly.

launchd accepts:

| Form | Example | Installed as |
| ---- | ------- | ------------ |
| Every hour on a minute | `0 * * * *` | hourly at `:00` |
| Daily at a time | `0 10 * * *` | daily 10:00 |
| Minute step dividing 60 | `*/15 * * * *` | `:00`, `:15`, `:30`, `:45` |
| Hour step dividing 24 | `0 */6 * * *` | 00:00, 06:00, 12:00, 18:00 |
| Weekly | `30 3 * * 0` | Sundays 03:30 |
| Monthly | `15 2 1 * *` | the 1st, 02:15 |

launchd rejects, with the reason named in the error:

- Ranges and lists in any field (`1-5`, `1,15`) — declare separate jobs.
- A month restriction (`0 9 1 6 *`).
- A step that does not divide its field evenly (`*/45`), because cron's uneven gaps have no uniform launchd equivalent.
- `day_of_month` and `day_of_week` both restricted (`0 9 1 * 1`), because cron ORs them and launchd ANDs them.
- Steps in more than one field at once.
- Values outside their cron range (`0 25 * * *`).

## `[hooks.<event>]`

The `[hooks]` table is keyed by the `config.toml` event name (`session_start`, `pre_compact`, `session_stop`, etc. — snake_case; see the [event glossary](../how/hooks.md#event-glossary) for the full mapping to Claude Code's own `SessionStart`/`Stop`/... names). Each event sub-table takes:

| Field      | Type                     | Default | Required | Description                                                                                                                          |
| ---------- | ------------------------ | ------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts`  | list of strings          | `[]`    | no       | Bare built-in hook names to run for this event, in order (e.g. `context-inject`, not `lh hook context-inject`). A name that does not resolve against the built-in registry or a user hook is silently skipped. |
| `external` | list of strings / tables | `[]`    | no       | Commands owned by a third-party tool, emitted to **every** profile after the built-ins. A bare string inherits the event's default matcher; a table pins its own (`{ command = "...", matcher = "..." }`). |

Example:

```toml
[hooks.session_start]
scripts = ["context-inject"]

[hooks.session_stop]
scripts = ["compound-loop"]
```

### `external` — hooks owned by another tool

A third-party tool that installs its own Claude Code hooks writes them into whichever profile its installer happened to run against, and rewrites them on every upgrade. Declaring them here makes the harness the source of truth: they deploy to every profile, in a schema Claude Code accepts.

```toml
[hooks.user_prompt_submit]
external = ["/usr/local/bin/some-tool hook"]

[[hooks.pre_tool_use.external]]
command = "/usr/local/bin/some-tool hook"
matcher = "AskUserQuestion"
```

`lh deploy` also preserves hook entries it finds in a profile but does not manage, on every event — including events the harness has no concept of — and reports each one. If such an entry carries a field Claude Code's schema rejects (a `null` matcher, say), deploy repairs it and says so: the agent skips an invalid settings file **in its entirety**, so one bad field silently disables every hook in that profile. `lh selftest` checks the same schema, since a failure that stops hooks from running cannot be detected by a hook.

### `[hooks.pre_tool_use]` — security hook overrides

The `pre_tool_use` event has one extra field on top of `scripts`, used by the built-in `pre-tool-use-security` hook to rescue specific commands from its block list. Mechanics: [how hooks work — pre-tool-use-security](../how/hooks.md#pre-tool-use-security-runs-on-pretooluse).

| Field            | Type            | Default | Required | Description                                                                                                                                                                                                                                                            |
| ---------------- | --------------- | ------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `allow_patterns` | list of strings | `[]`    | no       | Python `re.search` regexes. A command that matches a built-in block rule **and** any of these patterns is allowed through. Patterns are consulted only after a block rule already matched — a pattern with no matching block rule is dead config (harmless, useless). |

```toml
[hooks.pre_tool_use]
allow_patterns = [
    # Allow `terraform destroy` only against the test workspace
    "terraform\\s+destroy.*-target=module\\.scratch",
]
```

Rules:

- Patterns are full regexes (not glob). Escape backslashes per TOML.
- Broken regexes are silently skipped — they cannot turn the hook into a hard error.
- If `config.toml` cannot be read, the allowlist is empty. Fail-safe: stricter blocking, never weaker.

## `[compound_loop]`

| Field                          | Type           | Default                       | Required | Description                                                                                                                                                                                            |
| ------------------------------ | -------------- | ----------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `enabled`                      | bool           | `false`                       | no       | Whether the compound-loop hook fires.                                                                                                                                                                  |
| `model`                        | string         | `"claude-haiku-4-5-20251001"` | no       | Model used to distill learnings.                                                                                                                                                                       |
| `min_messages`                 | int            | `4`                           | no       | Floor on session length before the loop runs.                                                                                                                                                          |
| `min_user_chars`               | int            | `200`                         | no       | Floor on total user-message chars before the loop runs.                                                                                                                                                |
| `debounce_seconds`             | int            | `60`                          | no       | Minimum gap between two loop firings on the same session.                                                                                                                                              |
| `reprocess_min_growth_seconds` | int            | `120`                         | no       | Minimum seconds of JSONL growth since the last `done/` task before a `Stop` event re-queues. Bypassed by the `session-end` producer and `lh knowledge handoff-now`. See [ADR-019](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/019-handoff-session-end-freshness.md). |
| `timeout_seconds`              | int            | `120`                         | no       | Hard timeout on the loop's model call.                                                                                                                                                                 |
| `grading_enabled`              | bool           | `true`                        | no       | When true, the worker also runs the asynchronous response-grading pass alongside distillation. See [ADR-021](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/021-async-response-grading.md). |
| `lazymind_dir`                 | string / null  | `null`                        | no       | Optional override for the LazyMind-style knowledge root used by the loop. `null` disables the vault lookup. It is deliberately independent of `[knowledge].root`.                                                                    |
| `slim_handoff_enabled`         | bool           | `true`                        | no       | When true and the loop's gates block evaluation, a deterministic fast-path still writes `handoff.md` — branch, last user prompt, files touched — with no model call. See [ADR-030](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/030-memory-stack-glue-layer.md). |
| `backend`                      | string         | `"claude"`                    | no       | LLM backend for the loop's inference calls: `claude`, `ollama`, `mlx`, or `openai-compatible`. See [ADR-033](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/033-llm-backend-abstraction.md). |
| `backend_options`              | table          | `{}`                          | no       | Options for the backend, under `[compound_loop.backend_options]`. `base_url` (required for `openai-compatible`, preset for `ollama`/`mlx`) and `api_key` (default `"none"`).                          |

### Choosing an LLM backend

The compound loop's inference calls are decoupled from the agent you run. The default backend shells out to the `claude` binary; any OpenAI-compatible endpoint (Ollama, MLX serve, LM Studio, OpenRouter, ...) works as a drop-in replacement:

```toml
[compound_loop]
backend = "claude"                    # default, unchanged behaviour
model   = "claude-haiku-4-5-20251001" # default, unchanged

# Opt into Ollama — only these two lines change:
# backend = "ollama"
# model   = "llama3.2:3b"

# Custom OpenAI-compatible endpoint:
# backend = "openai-compatible"
# model   = "mistral-nemo"
# [compound_loop.backend_options]
# base_url = "http://my-gpu-box:11434"
# api_key  = "sk-..."
```

The `ollama` and `mlx` aliases preset `base_url` to `http://localhost:11434` and `http://localhost:8080` respectively; `backend_options.base_url` overrides the preset. `lh doctor` reports whether the configured backend is usable (binary on PATH for `claude`, endpoint reachable for the HTTP backends).

## `[lazynorth]`

| Field           | Type          | Default          | Required | Description                                              |
| --------------- | ------------- | ---------------- | -------- | -------------------------------------------------------- |
| `enabled`       | bool          | `false`          | no       | Whether LazyNorth context injection is active.           |
| `path`          | string (path) | `""`             | no       | Root of the LazyNorth directory.                         |
| `universal_doc` | string        | `"LazyNorth.md"` | no       | Default LazyNorth doc filename. Overridable per-profile. |

## `[context_inject]`

| Field                  | Type | Default | Required | Description                                                     |
| ---------------------- | ---- | ------- | -------- | --------------------------------------------------------------- |
| `enabled`              | bool | `true`  | no       | Whether the SessionStart hook injects context into the session. |
| `max_body_chars`       | int  | `3000`  | no       | Cap on injected body length.                                    |
| `last_session_enabled` | bool | `true`  | no       | Whether to include a digest of the previous session.            |
| `qmd_suggest_enabled`  | bool | `true`  | no       | Whether the branch name is used to pull related notes out of the search index. |
| `qmd_suggest_top_k`    | int  | `3`     | no       | How many suggestions that lookup returns.                       |
| `graphify_surface_enabled` | bool | `true` | no    | Whether the code-structure summary for the current repo is injected. |
| `proposals_summary`    | bool | `true`  | no       | Whether a one-line summary of pending claude-md proposals is emitted even when the full proposals section is dropped to fit the char budget. |
| `repo_map_scope`       | str  | `""`    | no       | Directory tree whose sessions receive the repo-map doc. Empty disables the section; a session whose cwd is outside the tree never pays for it. |
| `repo_map_doc`         | str  | `"docs/repos.md"` | no | Path to the map, relative to the agent runtime dir. Only read when `repo_map_scope` is set. |
| `repo_map_max_chars`   | int  | `1200`  | no       | Cap on the injected map, cut on a line boundary with the remainder announced. Keeps a long map from starving every other section of the body budget. |

## Environment variable overrides

Three env vars relocate the directories `lazy-harness` reads and writes. They take precedence over XDG vars and platform defaults.

| Env var         | Overrides        | Default (macOS/Linux)         |
| --------------- | ---------------- | ----------------------------- |
| `LH_CONFIG_DIR` | Config directory | `~/.config/lazy-harness`      |
| `LH_DATA_DIR`   | Data directory   | `~/.local/share/lazy-harness` |
| `LH_CACHE_DIR`  | Cache directory  | `~/.cache/lazy-harness`       |

XDG fallbacks (`XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`) are honored when the explicit `LH_*` vars are unset.

## Reloading config

There is nothing to reload — every `lh` invocation re-parses `config.toml` from disk, so saving the file is the entire reload step.
