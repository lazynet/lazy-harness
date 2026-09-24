# Engram 1.20.0 → 2.1.0 migration

Status: **proposed** (phase 1, research and plan only — nothing upgraded).
Date: 2026-09-24. Scope: the Mac (Homebrew) and the homelab CT `agents`
(lazy-ansible `agent_station` role).

Every claim below carries the command or file that produced it. Source
comparisons were read from a clone of `Gentleman-Programming/engram` at tags
`v1.20.0`, `v2.0.0`, `v2.1.0`; release notes from `gh release view`.

## 1. What changes between 1.20.0 and 2.1.0

2.0.0 is 462 commits past 1.20.0 (release notes, `v2.0.0`). 2.1.0 is the current
stable (`gh release list`: `v2.1.0 Latest 2026-09-23`), and `brew info engram`
offers `1.20.0 → stable 2.1.0`.

### 1.1 Database

- **Additive migrations, stamped.** 2.x introduces `PRAGMA user_version` with
  `schemaVersion = 1` (`internal/store/store.go`, `runStartupMigrations`).
  Both hosts read `user_version = 0` today. A binary seeing a *newer* version
  skips migrations, so 2.x never writes a schema newer than itself.
- New tables: `sync_delete_tombstones`, `sync_delete_tombstone_remote_floors`
  (diff of `CREATE TABLE IF NOT EXISTS` across tags).
- New columns via `addColumnIfNotExists`: `sessions.ownership_mode`,
  `sessions.runtime_lease_expires_at`, `sync_state.last_success_at`, several on
  `sync_mutations` and `sync_apply_deferred` (`git diff v1.20.0 v2.1.0 --
  internal/store/store.go`).
- **FTS rebuild.** The observation and prompt FTS tables and their triggers are
  dropped and rebuilt when their definition does not match — the new triggers
  honour `deleted_at`. On the Mac store (24 410 observations) the first open is
  a full reindex; expect a slow first start.
- **Consequence for rollback:** a 1.20.0 binary on a migrated DB is untested
  territory (different FTS triggers, NULL ownership on rows it writes). Rollback
  is *restore the file*, never *downgrade the binary in place*.
- Data dir unchanged: `~/.engram/engram.db`, `ENGRAM_DATA_DIR` override.
- 2.1.0 upgrades SQLite with a WAL-reset fix and takes write locks at
  transaction start; the DB must stay on a local filesystem (#1292).

### 1.2 CLI

- New subcommands in 2.1.0: `hook`, `init`, `rescue-ownership`, `instance-id`,
  plus `setup claude-code --mcp-only` (`case` labels in `cmd/engram/main.go` at
  each tag). Nothing removed.
- **Read scoping (breaking):** an omitted project now resolves the current
  project instead of reading all projects; `--all` / `all_projects=true` is
  explicit. Ambiguous cwd detection fails instead of guessing (release notes,
  "Breaking and compatibility changes").
- `engram save <title> <content> --type T --project P --scope S` — the exact
  call `engram-persist` makes — is still accepted. With an explicit `--project`
  resolution cannot be ambiguous. New behaviour: titleless saves are rejected
  (`store.ValidateObservationTitle`; `_build_title` never produces an empty
  title), a normalization warning may go to stderr, and each save now creates
  or reuses a `manual-save-<project>` session with `project_owned` ownership.
- `engram version` / `--version` still print `engram <ver>`.

### 1.3 MCP

- Tool set 1.20.0: 22 tools. 2.1.0 adds `mem_list_projects`; nothing renamed or
  removed (`NewTool("mem_…")` across tags). Existing permission allowlists in
  `settings.json` (`mcp__engram__mem_*`) stay valid.
- 2.1.0 adds atomic find-and-replace on observations via MCP/HTTP (#1342).
- Runtime-bound session attribution for Claude Code writes (#1352).

### 1.4 Claude Code plugin

- Plugin version per tag: `v1.20.0` ships `0.1.1`, `v2.0.0` and `v2.1.0` ship
  `0.1.3` (`plugin/claude-code/.claude-plugin/plugin.json`).
- `0.1.3` `session-start.sh` calls `engram setup claude-code --mcp-only` **on
  every session start**. In 2.x that inspects
  `$CLAUDE_CONFIG_DIR/.claude.json` and, if `mcpServers.engram` is absent, runs
  `claude mcp add --scope user engram -- <engram> mcp --tools=agent`; if present
  but different it prints a conflict to stderr and changes nothing
  (`internal/setup/setup.go`, `EnsureClaudeCodeUserMCP`).
- **Server ownership check (new, operationally critical).** `0.1.3` only
  trusts a server on `127.0.0.1:7437` whose `/health` returns an `instance_id`
  equal to `engram instance-id`. A 1.20.0 `engram serve` left running returns
  no `instance_id`, the plugin fails to bind a new one on the busy port, prints
  `Engram server ownership mismatch` and **exits without session registration
  or context injection** (`plugin/claude-code/scripts/_helpers.sh`,
  `engram_health_matches_instance`). The old `serve` must be killed.
- New `PreToolUse` hook `engram hook claude-pre-tool-use` on `mem_*` writes —
  the subcommand only exists in 2.x.

### 1.5 Codex

2.1.0 ships a Codex plugin and a native `engram hook codex-user-prompt-submit`.
Neither is installed here; Codex only reaches engram through lazy-harness's
`engram-persist` hook (§2). No change required.

### 1.6 Sync / Cloud

Cloud autosync is opt-in and project-scoped; `sync --cloud --all` is rejected.
Neither host uses it: `engram cloud status` → `not configured` on the Mac, and
`config.toml` sets `git_sync = false`, `cloud = false`. The Mac `serve.err.log`
shows `autosync disabled` (no token). There is **no Mac↔CT engram sync**: each
host has its own store; what they share is the distilled JSONL in
lazy-knowledge, which `engram-persist` mirrors into each local store.

## 2. Inventory of consumers

### lazy-harness (this repo)

| Consumer | Where | Touches engram how | 2.x impact |
| --- | --- | --- | --- |
| Version pin | `src/lazy_harness/memory/engram.py:3,14` | `PINNED_VERSION = "1.20.0"` | bump |
| Config default | `src/lazy_harness/core/config.py:20,326,647` | `EngramConfig.version` defaults to the pin | follows pin |
| Capability registry | `src/lazy_harness/plugins/builtins.py:36-44` | `pinned_version=engram.PINNED_VERSION` — `lh doctor` drift | follows pin |
| Feature probe | `src/lazy_harness/features.py:49-59` | `engram --version` | output format unchanged |
| `check_version()` | `src/lazy_harness/memory/engram.py:51-66` | `engram --version` | unchanged |
| MCP entry | `src/lazy_harness/memory/engram.py:46-48`, `deploy/engine.py:707-708` | `{"command":"engram","args":["mcp"]}`, only if `[memory.engram].enabled` | disabled on both hosts; if ever enabled, 2.x's exact-match check reports it as a **conflict** (expects `--tools=agent`, absolute path) |
| `run_engram()` | `src/lazy_harness/memory/engram.py:35` | generic `engram <action> --project` | no caller in `src/` — dead code, mention only |
| engram-persist hook | `hooks/builtins/engram_persist.py:18-45,125-152`, `knowledge/engram_persist.py:132-160,297-310` | `engram save … --project <git-common-dir parent> --scope project`; `engram version` for metrics | contract kept (§1.2); probe before trusting |
| Hook registry | `hooks/loader.py:119` | registers `engram-persist` | none |
| Persist health | `monitoring/engram_persist_health.py`, `cli/doctor_cmd.py:196-249,1236` | reads `engram_persist_metrics.jsonl` | none |
| Wizard | `wizards/memory.py:25-63` | prints/writes the pin | follows pin |
| Compound-loop prompt | `knowledge/compound_loop.py:919` | prose about `mem_save` | none |
| Docs | `docs/reference/config.md:225`, `specs/adrs/022-engram-episodic-memory.md:41` | name `1.20.0` | update with the pin |
| Tests naming 1.20.0 | `tests/unit/test_engram.py:60,68,72`, `tests/unit/test_features.py:64,72,73,84`, `tests/unit/test_config.py:482,517,525,962`, `tests/unit/wizards/test_memory.py:96`, `tests/core/test_versions.py:14` | fixtures | update under TDD |

### Machine config (Mac)

- `~/.config/lazy-harness/config.toml:167-176` — `[memory.engram] enabled =
  false`, `version = "1.20.0"`, `binary = "/opt/homebrew/bin/engram"`;
  `engram-persist` listed in `[hooks.session_stop]` (line 72). Chezmoi-managed.
- `~/.claude-lazy/.claude.json` and `~/.claude-flex/.claude.json` —
  `mcpServers.engram = {"type":"stdio","command":"/opt/homebrew/bin/engram","args":["mcp","--tools=agent"]}`
  (written by engram, not by `lh deploy`).
- `~/.claude-lazy/settings.json:111+` — `mcp__engram__mem_*` allowlist.
- Claude plugin `engram@engram` from marketplace `Gentleman-Programming/engram`
  (tracks the repo's default branch, last updated 2026-09-23): **0.1.2** active
  in both Claude profiles (`installed_plugins.json`, user + project scope), 0.1.3
  already in the claude-lazy cache.
- `~/.codex-lazy/hooks.json` — `lh hook engram-persist --profile codex-lazy`
  (Stop). No engram MCP in `~/.codex-lazy/config.toml`.
- Processes: one orphaned `engram serve` (pid 9032, started 2026-09-20 by the
  plugin hook, parent 1) and six `engram mcp --tools=agent` children of live
  sessions. No launchd job runs engram (`launchctl list | grep -i engram` →
  empty; no plist names it).

### CT `agents` (lazy-ansible)

- `roles/agent_station/defaults/main.yaml:578-613` — `agent_station_engram_version:
  "1.20.0"`, sha256 per arch; comment explains why it tracks the Mac.
- `roles/agent_station/tasks/main.yaml:789-822` — idempotence check is
  `engram --version` containing the pinned string; installs the release
  tarball into `~/.local/bin`. It does not manage `engram serve`.
- Host: `ssh lazy-agents` (x86_64 → `amd64` asset). `engram 1.20.0`.
- Plugin: claude-lazy **0.1.1**; claude-flex's `installed_plugins.json` says
  0.1.3 but `~/.claude-flex/plugins/cache/engram/` **does not exist** (broken
  install). Neither profile's `.claude.json` has `mcpServers.engram` — CT
  sessions have no engram MCP tools today.
- `~/.codex-lazy/hooks.json` references engram (`engram-persist`).
- One `engram serve` (pid 2021292, started 2026-09-23). No systemd unit, no
  crontab entry.

## 3. The `engram setup` menu at SessionStart

Cause: the engram Claude plugin **0.1.2**, running against a **1.20.0** binary.

1. `~/.claude-lazy/plugins/cache/engram/engram/0.1.2/scripts/session-start.sh:22-29`
   runs `engram setup claude-code --mcp-only` whenever
   `$HOME/.claude/mcp/engram.json` is missing or a symlink. That path is never
   right under `CLAUDE_CONFIG_DIR=~/.claude-lazy`, and `~/.claude/mcp/` does not
   exist, so it runs on **every** session start, in both profiles.
2. 1.20.0 does not know `--mcp-only`. Its `cmdSetup` treats an unknown
   hyphen flag as "fall back to the interactive menu"
   (`v1.20.0:cmd/engram/main.go`, `case unknownFlagSeen: cmdSetupInteractive`).
   The menu goes to stdout, which Claude Code injects as SessionStart context;
   stdin is already drained by `INPUT=$(cat)`, so the prompt reads EOF and
   nothing is installed.
3. Why the skew exists: the marketplace follows the engram repo's default
   branch, which carried v2 release candidates since late August, while the
   binary stayed on the 1.20.0 stable. The plugin moved ahead; the binary did not.

Does 2.x fix it? Yes, by construction: 2.1.0 parses `--mcp-only`
(`v2.1.0:cmd/engram/main.go:3248`) and calls `EnsureClaudeCodeUserMCP`, which
is silent on an exact match. Two things to verify after the upgrade rather than
assume: that `canonicalEngramCommand` maps the Cellar path back to
`/opt/homebrew/bin/engram` (otherwise the existing entry is reported as a
*conflict* on stderr every session — noisy, harmless), and that the plugin is
moved to 0.1.3 so the mismatched 0.1.2 check disappears.

## 4. Baseline (captured 2026-09-24, read-only)

Counts via `sqlite3 "file:~/.engram/engram.db?mode=ro"`; diagnostics via
`engram doctor --json` (read-only per its help). Both hosts ran a dedupe
earlier today (`~/.engram/dedupe-done.txt`: Mac `deleted=6741`, CT
`deleted=525`) — re-snapshot immediately before migrating.

| Metric | Mac | CT `agents` |
| --- | --- | --- |
| Binary | `/opt/homebrew/bin/engram` 1.20.0 | `~/.local/bin/engram` 1.20.0 |
| DB | `~/.engram/engram.db` 409 MB + 11 MB WAL | `~/.engram/engram.db` 14 MB + 4 MB WAL |
| `user_version` | 0 | 0 |
| observations (all / live) | 24 410 / 12 651 | 2 267 / 1 742 |
| sessions | 6 001 | 65 |
| prompts | 5 629 | 46 |
| distinct projects | 54 | 3 |
| latest observation | 2026-09-24 15:42:35 | 2026-09-23 16:03:09 |
| `engram doctor` | **blocked**: `sync_mutation_required_fields` 423 (observation upserts missing `title`); warnings: `session_project_directory_mismatch` 447, `manual_session_name_project_mismatch` 2 | ok (all four checks) |
| `sync_mutations` rows | 90 064 | not measured |
| Existing backups | `engram-backup-2026-09-24-pre-dedupe.db`, `…-pre-dedupe-all.db` | `…-pre-dedupe-all.db` |

The Mac's blocked finding concerns the Cloud replication queue, which is not
in use; it predates this migration and is a user decision (§6).

## 5. Migration plan

### 5.1 Order

**CT first, as canary; Mac second.** The CT store is 18× smaller, doctor is
clean, it has one Claude user, and its install is declarative. There is no
shared store, so the two hosts running different versions for a while writes
no incompatible data *between* them — `engram-persist` on each host only
writes its own local DB from the shared JSONL. The real "two versions" hazard
is **within** a host: a live 1.20.0 `mcp`/`serve` process writing into a DB a
2.x process has just migrated. Every step therefore stops all engram
processes on the host before the binary changes.

### 5.2 lazy-harness changes (TDD, one PR, merged before either host moves)

Probes first, per the AGENTS.md gate on external binaries: run 2.1.0 from the
release tarball against a **copy** of each DB in a scratch `ENGRAM_DATA_DIR`,
record observed behaviour in `specs/designs/engram-evidence.md`, then write
the tests.

1. **Probe `save` under 2.1.0** — exit code, stdout (`Memory saved: #N …`),
   stderr (normalization warning), the `manual-save-<project>` session row,
   from a git worktree cwd and a non-git cwd. Red test in
   `tests/unit/test_engram_persist*.py` only if behaviour differs.
2. **Bump `PINNED_VERSION` to `2.1.0`** — failing test first
   (`tests/unit/test_engram.py:60`), then the constant, then every fixture that
   pins the literal (§2 table), `docs/reference/config.md:225`, and an
   Evolution bullet in ADR-022.
3. **Align `mcp_server_config()` with engram's own entry** —
   `{"command": <absolute engram>, "args": ["mcp", "--tools=agent"]}`, so
   enabling `[memory.engram]` does not trip 2.x's conflict check. Test asserts
   the args.
4. **Doctor: plugin/binary skew** (optional, backlog candidate) — report when
   the installed `engram@engram` plugin version is newer than the one the
   binary's tag ships. This skew is what produced the menu.
5. **`lh doctor` smoke** after the pin bump on a 2.1.0 binary: no drift line.

`run_engram()` has no caller; mention, do not touch.

### 5.3 CT `agents`

Backup (as `lazynet` on the CT):

```bash
pkill -f 'engram (serve|mcp)'            # after closing agent sessions on the CT
pgrep -fl engram || echo none            # expect: none
mkdir -p ~/.engram/pre-v2
sqlite3 ~/.engram/engram.db ".backup '$HOME/.engram/pre-v2/engram.db'"
sqlite3 ~/.engram/pre-v2/engram.db 'PRAGMA integrity_check'   # expect: ok
cp ~/.local/bin/engram ~/.engram/pre-v2/engram-1.20.0
~/.local/bin/engram export ~/.engram/pre-v2/engram-export.json
```

Upgrade through lazy-ansible, not by hand — branch in lazy-ansible:

```yaml
# roles/agent_station/defaults/main.yaml
agent_station_engram_version: "2.1.0"
agent_station_engram_sha256:
  amd64: 3579cf5d92ae9349c6941ff08cde04012b12c9c695d307e71afaee4fb5e4a9c1
  arm64: 12b84e62a9763290d086efc0332dfbd9ebe2f3ff7461c44ed091c9f946d2f0cc
```

Those hashes come from the release's `checksums.txt`; per the role's own
comment, verify them against the downloaded asset before committing. Also
update the defaults comment (the doctor-pin paragraph is stale) and consider a
task that stops a running `engram serve` after an install changes the binary.
Apply with the repo's usual `ansible-playbook` invocation limited to `agents`
and the `agent_station` role.

Then, in each Claude profile on the CT: `claude plugin update engram@engram`
(target 0.1.3; claude-flex needs a reinstall — its cache is missing). First
session start will run `engram setup claude-code --mcp-only` and **add**
`mcpServers.engram` to each profile's `.claude.json`, which the CT does not
have today.

### 5.4 Mac

Close every Claude/Codex session (the six `engram mcp` children die with
them), then:

```bash
pkill -f 'engram (serve|mcp)'; pgrep -fl engram || echo none
mkdir -p ~/.engram/pre-v2
sqlite3 ~/.engram/engram.db ".backup '$HOME/.engram/pre-v2/engram.db'"
sqlite3 ~/.engram/pre-v2/engram.db 'PRAGMA integrity_check'
cp "$(readlink -f /opt/homebrew/bin/engram)" ~/.engram/pre-v2/engram-1.20.0
engram export ~/.engram/pre-v2/engram-export.json
HOMEBREW_NO_INSTALL_CLEANUP=1 brew upgrade gentleman-programming/tap/engram
```

`HOMEBREW_NO_INSTALL_CLEANUP=1` keeps the 1.20.0 keg; the copied binary is the
second rollback path. Disk: the Mac already holds ~800 MB of pre-dedupe
backups in `~/.engram/`; the new backup adds ~410 MB.

Then `claude plugin update engram@engram` in claude-lazy and claude-flex
(target 0.1.3), `lh` release with §5.2 installed via `uv tool install
--reinstall`, and `version = "2.1.0"` in `config.toml` through chezmoi.

### 5.5 Verification (per host, in this order)

| Step | Command | Expected |
| --- | --- | --- |
| Binary | `engram version` | `engram 2.1.0` |
| First open migrates | `engram doctor --json \| jq .status` | runs to completion (first run may be slow: FTS rebuild) |
| Schema stamped | `sqlite3 "file:$HOME/.engram/engram.db?mode=ro" 'PRAGMA user_version'` | `1` |
| No data loss | counts query from §4 | observations / sessions / prompts ≥ pre-migration snapshot, live count equal |
| Doctor delta | `engram doctor --json` | no blocking finding absent from the baseline |
| Server identity | `curl -s 127.0.0.1:7437/health \| jq -r .instance_id` vs `engram instance-id` | equal (after the first session start spawns `serve`) |
| Menu gone | start a session; read the SessionStart hook output file | no `engram setup — Install agent plugin` |
| MCP registration | `jq .mcpServers.engram $CLAUDE_CONFIG_DIR/.claude.json` | the stdio entry; no `conflict` line on hook stderr |
| MCP works | `mem_search` for a known title, `mem_save` + `mem_get_observation` round trip | hit / saved id returned |
| engram-persist | append one entry to a test project's `decisions.jsonl`, fire the Stop hook, read `engram_persist_metrics.jsonl` and `engram search --project <p>` | success metric, observation found |
| lh doctor | `lh doctor` | no engram drift line, persist health ok |

### 5.6 Rollback (per host)

1. Stop all engram processes (`pkill -f 'engram (serve|mcp)'`).
2. Restore the binary: Mac `cp ~/.engram/pre-v2/engram-1.20.0` over the linked
   binary or `brew link` the kept 1.20.0 keg; CT revert the lazy-ansible commit
   and re-apply, or copy `~/.engram/pre-v2/engram-1.20.0` to `~/.local/bin/engram`.
3. Restore the DB: move `engram.db`, `-wal`, `-shm` aside, copy
   `~/.engram/pre-v2/engram.db` back. Never run 1.20.0 against the migrated file.
4. Plugin back to the version the binary ships (0.1.1 for 1.20.0 — which also
   removes the menu, since 0.1.1 never calls `--mcp-only`).
5. Anything saved between upgrade and rollback is lost from the store; the
   JSONL side of `engram-persist` re-mirrors on the next Stop only if its
   cursor is reset — note which entries fall in the window.

### 5.7 Kill criteria

Roll back the host if, within 24 h of its upgrade, any of:

- live observation count drops below the pre-migration snapshot;
- `engram doctor` reports a blocking finding not present in the baseline;
- any `engram-persist` run records a failure (`engram_persist_metrics.jsonl`)
  that 1.20.0 did not produce for the same input;
- SessionStart shows `Engram server ownership mismatch` or no memory context
  after the stale `serve` was killed;
- MCP `mem_save`/`mem_search` fail twice in a fresh session.

CT failing any criterion blocks the Mac step.

## 6. Decisions for the user

1. **Order** — CT canary then Mac (recommended), or Mac first because that is
   where the menu bug lives.
2. **Mac's 423 blocked `sync_mutations`** (titleless observation upserts in
   the Cloud queue; Cloud unused) — leave them, or run 2.x `engram doctor`
   repair / `engram cloud upgrade doctor` after the upgrade. Recommend leave:
   nothing consumes the queue.
3. **Plugin source** — keep the marketplace on the default branch (the source
   of today's skew), or pin it to the `v2.1.0` tag. Pinning needs a check that
   Claude Code's marketplace `github` source honours a `ref`; not verified here.
4. **CT MCP** — accept that the 2.x plugin will register engram MCP in both CT
   Claude profiles on first start (new capability there), or suppress it.
5. **Target** — 2.1.0 (recommended: stable, SQLite WAL fix) vs 2.0.0.
