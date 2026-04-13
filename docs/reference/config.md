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

[hooks.SessionStart]
scripts = ["lh hook session-context"]

[hooks.Stop]
scripts = ["lh hook compound-loop"]

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

| Field  | Type          | Default | Required | Description                                         |
| ------ | ------------- | ------- | -------- | --------------------------------------------------- |
| `path` | string (path) | `""`    | no       | Root of the knowledge directory. Empty disables it. |

`[knowledge.sessions]`:

| Field     | Type   | Default      | Required | Description                                           |
| --------- | ------ | ------------ | -------- | ----------------------------------------------------- |
| `enabled` | bool   | `false`      | no       | Whether session export writes into the knowledge dir. |
| `subdir`  | string | `"sessions"` | no       | Subdirectory under `knowledge.path`.                  |

`[knowledge.learnings]`:

| Field     | Type   | Default       | Required | Description                                             |
| --------- | ------ | ------------- | -------- | ------------------------------------------------------- |
| `enabled` | bool   | `false`       | no       | Whether the compound loop persists distilled learnings. |
| `subdir`  | string | `"learnings"` | no       | Subdirectory under `knowledge.path`.                    |

`[knowledge.search]`:

| Field    | Type   | Default | Required | Description                                       |
| -------- | ------ | ------- | -------- | ------------------------------------------------- |
| `engine` | string | `"qmd"` | no       | Search backend. Only `qmd` is implemented today. |

## `[monitoring]`

| Field     | Type          | Default | Required | Description                                                                                                                    |
| --------- | ------------- | ------- | -------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `enabled` | bool          | `false` | no       | Whether the monitoring pipeline writes to SQLite.                                                                              |
| `db`      | string (path) | `""`    | no       | Path to the monitoring DB. Empty falls back to the data dir default.                                                           |
| `pricing` | table         | `{}`    | no       | Per-model pricing for cost rollups, e.g. `[monitoring.pricing.<model>]` with `input` / `output` USD-per-million-tokens floats. |

## `[scheduler]` and `[scheduler.jobs.<name>]`

| Field     | Type   | Default  | Required | Description                                                                           |
| --------- | ------ | -------- | -------- | ------------------------------------------------------------------------------------- |
| `backend` | string | `"auto"` | no       | Scheduler backend. `auto` picks launchd (macOS), systemd (Linux), or cron (fallback). |

Each `[scheduler.jobs.<name>]` sub-table:

| Field      | Type   | Default | Required | Description                                              |
| ---------- | ------ | ------- | -------- | -------------------------------------------------------- |
| `schedule` | string | —       | yes      | Cron-style schedule expression. Missing → `ConfigError`. |
| `command`  | string | —       | yes      | Shell command to run on each fire. Missing → `ConfigError`. |

The job's `name` is the TOML key — there is no `name` field inside the table.

## `[hooks.<event>]`

The `[hooks]` table is keyed by Claude Code hook event name (`SessionStart`, `PreCompact`, `Stop`, `UserPromptSubmit`, etc.). Each event sub-table has a single field:

| Field     | Type            | Default | Required | Description                                                                         |
| --------- | --------------- | ------- | -------- | ----------------------------------------------------------------------------------- |
| `scripts` | list of strings | `[]`    | no       | Commands to run for this event, in order. Typically `lh hook <name>` for built-ins. |

Example:

```toml
[hooks.SessionStart]
scripts = ["lh hook session-context"]

[hooks.Stop]
scripts = ["lh hook compound-loop"]
```

## `[compound_loop]`

| Field              | Type   | Default                       | Required | Description                                                 |
| ------------------ | ------ | ----------------------------- | -------- | ----------------------------------------------------------- |
| `enabled`          | bool   | `false`                       | no       | Whether the compound-loop hook fires.                       |
| `model`            | string | `"claude-haiku-4-5-20251001"` | no       | Model used to distill learnings.                            |
| `min_messages`     | int    | `4`                           | no       | Floor on session length before the loop runs.               |
| `min_user_chars`   | int    | `200`                         | no       | Floor on total user-message chars before the loop runs.     |
| `debounce_seconds` | int    | `60`                          | no       | Minimum gap between two loop firings.                       |
| `timeout_seconds`  | int    | `120`                         | no       | Hard timeout on the loop's model call.                      |
| `learnings_subdir` | string | `"learnings"`                 | no       | Subdir under the knowledge dir where learnings are written. |

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
