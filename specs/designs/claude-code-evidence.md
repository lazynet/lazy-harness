# Claude Code dialect evidence — caller identification marker

**Status:** two probes recorded — 2026-09-24 against Claude Code 2.1.281, and
2026-09-29 against 2.1.284 (§ Headless isolation flags), 2026-10-09 against
2.1.295 and 2.1.283 (§ Hook `onFailure`), and 2026-11-01 against 2.1.316
(§ Evaluator isolation, § `lh exec` isolation).
**Scope:** the first section owns one fact only — the payload key `hooks/runner.py`'s
`_caller_agent` uses to tell a Claude Code hook invocation apart from a Codex
one (ADR-041, Evolution 2026-09-24; ADR-068, Evolution 2026-09-24). It is not
a full dialect probe in the shape of `specs/designs/codex-evidence.md`; it
states only what the runner docstring and `tests/unit/hooks/test_runner.py`
already record as observed, with no new probe run to produce it.

## Observed

**Claude Code 2.1.281 dump-hook probe, 2026-09-24.** A `PreToolUse` payload
sends `prompt_id` and does not send `turn_id` or `model`. Recorded in
`hooks/runner.py:93-99` (`_CALLER_MARKERS` docstring) and mirrored in
`tests/unit/hooks/test_runner.py:30-40` (`CLAUDE_PRE_TOOL_USE` fixture).

Contrast, for the same marker on the other side: Codex 0.154.0 sends
`turn_id` and `model` and no `prompt_id`, on `PreToolUse` — `specs/designs/
codex-evidence.md` §1, probe 5.

**What was not measured.** The probe covers `PreToolUse` only. The runner
docstring is explicit that other Claude Code events were not measured for
these markers, so `_caller_agent` cannot tell a caller apart on those events
either — an unidentified caller on an unknown profile refuses rather than
guesses (`hooks/runner.py:103`, `_fallback_profile`).

## Headless isolation flags — observed vs `--help`

**Claude Code 2.1.284, 2026-09-29, subscription (OAuth) auth.** Question: which
`claude -p` flags keep the compound-loop evaluator from booting the profile it
inherits — SessionStart and UserPromptSubmit hooks, plugin hooks, skill and MCP
listings — under the auth the evaluator actually runs with. `--bare` is ruled
out by its own help text ("Anthropic auth is strictly ANTHROPIC_API_KEY"); the
probe confirms it.

**Method.** Eight runs of
`claude -p --model claude-haiku-4-5-20251001 --output-format json <flags>` with
`CLAUDE_CONFIG_DIR=~/.claude-lazy`, prompt `Reply with the single word OK.` on
stdin, from an empty scratch directory. `json` output only to read the session
id and usage; the evaluator's argv stays `--output-format text`. For each run:
the transcript's `attachment` records (hook output and listings), the
transcript's `tool_use` blocks, and the side effects of the Stop and SessionEnd
hooks — a `session_closed` row in `metrics.db` and a task in the profile's
compound-loop queue. One sample per flag set.

| Flags | Exit | SessionStart / UserPromptSubmit hook output | `session_closed` row, queued task | Listings left |
| --- | --- | --- | --- | --- |
| none (the evaluator today) | 0 | 7 records / 1 | yes, yes | skills, MCP instructions, deferred tools, agents, instructions |
| `--setting-sources ""` | 0 | none / none | no, no | skills, MCP instructions, deferred tools, agents |
| `--strict-mcp-config` | 0 | 7 / 1 | yes, yes | MCP instructions gone; rest kept |
| `--disable-slash-commands` | 0 | 7 / 1 | yes, yes | skill listing gone; rest kept |
| `--tools ""` | 0 | 7 / 1 | yes, yes | deferred tools and agents gone |
| all four above | 0 | none / none | no, no | none |
| `--restricted` | 0 | none / none | no, no | skills, MCP instructions, deferred tools, agents |
| `--bare` | 1 | — | — | `Not logged in · Please run /login` |

**Observed vs help.**

- `--setting-sources ""` is not documented as taking an empty list (help: "user,
  project, local"). It is accepted, and it silences **plugin** hooks as well as
  settings hooks: the engram plugin's UserPromptSubmit output is gone with it,
  because plugins are enabled from the user settings it no longer loads. It is
  the one flag that alone removes every hook side effect.
- `--restricted` behaves the same for hooks — its help says it "ignores user,
  project and local settings files" — and additionally removes command-running
  tools; it leaves the listings.
- `--strict-mcp-config`, `--disable-slash-commands` and `--tools ""` each remove
  a listing and **no** hook. None of them alone stops the metrics pollution.
- **The baseline run took tool calls.** With hooks live, the one-word prompt
  produced 6 assistant records and two tool calls (`ToolSearch`,
  `mcp__engram__mem_context`) — the engram "CRITICAL FIRST ACTION" nudge acted
  on. Every hookless run produced 2 assistant records and no tool call. This is
  a candidate cause of the evaluator's output size, not measured on the
  evaluator itself.
- Usage per run: baseline 23,445 cache-write + 86,924 cache-read over its
  multiple turns; all four flags 6,637 cache-write, 0 read, one turn. Single
  samples with a warm or cold cache each; use them for order of magnitude only.

**What was not measured.** A real evaluator prompt under these flags (JSON
parse rate, grade yield); Codex-launched evaluations; `--no-session-persistence`,
deliberately, since it would also remove the evaluator's spend from metrics
(ADR-039 F7). *Superseded 2026-11-01: § Evaluator isolation measures it, and
the evaluator now runs with it.* The probe sessions themselves left a `session_closed` row and a
queued task for each hooked run, which the worker skips as non-interactive.


## Evaluator isolation — observed vs `--help`

**Claude Code 2.1.316, 2026-11-01, subscription (OAuth) auth.** Question: which
argv lets `ClaudeBackend` run the compound-loop evaluator with no hook of any
kind — settings or plugin — and no artifact a consumer can read as a user
session. Re-run because the 2026-09-29 answer was never shipped and the
evaluator was still polluting: Engram held 3,611 copies of the evaluator prompt
as user prompts (first 2026-08-10, last 2026-11-02 00:38 UTC), and
`is_evaluator_session` matched 706 of the 1,088 top-level JSONLs under
`~/.claude-lazy/projects/`, 697 of them present in `metrics.db`
`session_stats` (`claude-haiku-4-5-20251001` and `claude-haiku-5-5`,
api-equivalent USD 19.43 summed).

**Method.** One run per flag set of
`claude -p --model claude-haiku-5-5 --output-format text <flags>` — the
evaluator's argv — with `CLAUDE_CONFIG_DIR=~/.claude-lazy`, prompt
`probe-<uuid> reply with the single word OK.` on stdin, from an empty scratch
directory, then 20 s for the async hooks. Observed per run: exit and output;
Engram `user_prompts` rows containing the marker; compound-loop tasks naming
the scratch cwd in `queue/` or `queue/done/`; JSONLs under `projects/`
containing the marker, with their `attachment` and hook record counts; files
under the knowledge store's `sessions/` containing the marker.

| Run | Flags | Exit, stdout | Engram row | Queued tasks | Transcript (attachments / hook records) | Export |
| --- | --- | --- | --- | --- | --- | --- |
| a | none (the argv until this change) | 0, `OK` | 1 | 2 (Stop + SessionEnd) | yes (23 / 8) | none |
| b | `--settings '{"disableAllHooks": true}'` | 0, `OK` | 0 | 0 | yes (16 / 0) | none |
| c | b + `--no-session-persistence` | 0, `OK` | 0 | 0 | **none** | none |
| d | `--bare` | 1, `Not logged in · Please run /login` | 0 | 0 | yes (3 / 0) | none |
| e | `--setting-sources ""` | 0, `OK` | 0 | 0 | yes (13 / 0) | none |
| f | e + `--no-session-persistence` | 0, `OK` | 0 | 0 | **none** | none |
| g | c, streams split | 0, stdout `OK` | — | — | — | — |
| h | f through `ClaudeBackend.complete` | returns `'OK'` | 0 | 0 | none | — |

**Observed vs help and spec.**

- `--bare` fails under OAuth, as its help says ("Anthropic auth is strictly
  ANTHROPIC_API_KEY") — and it still writes a transcript of the failed run.
- `disableAllHooks` passed through `--settings` also silences **plugin** hooks
  (Engram's `UserPromptSubmit` stored nothing), which the settings docs do not
  state. It prints a plugin notice on every run — `moshi-hook: hooks module not
  loaded: only managed plugins and built-in plugins run (allowManagedHooksOnly /
  disableAllHooks)` — on **stderr** (run g), so stdout stays parseable. The
  notice's own wording says managed and built-in plugin hooks still run.
- `--setting-sources ""` behaves as recorded on 2.1.284: accepted though the
  help lists only `user, project, local`, and silences settings and plugin hooks
  alike, because plugins are enabled from the user settings it does not load.
  No stderr notice. This is the flag `ClaudeBackend` ships.
- Neither hook flag stops the transcript. `--no-session-persistence` does, in
  both combinations (runs c, f, h) — it is the only flag here that keeps the
  evaluator out of `projects/`, and with it out of session export, the compound
  loop and metrics ingest.
- **Cost of `--no-session-persistence`.** The evaluator's spend reached
  `session_stats` only through those transcripts (697 rows above). With them
  gone, `ClaudeBackend` spend is unrecorded until `run_inference` writes usage
  itself, which the text output format does not carry (ADR-039, *Not
  implemented*).

**What was not measured.** A real evaluator prompt under the shipped flags
(JSON parse rate, grade yield); managed-policy hooks, which this host does not
have; the second `claude -p` argv, `ClaudeCodeAdapter.headless_argv`, behind
`lh exec`, which was unchanged and still booted the profile (*measured and
isolated 2026-11-01: § `lh exec` isolation*). One sample per flag
set; two extra baseline runs came from debugging the probe script, so the
probe left three Engram rows, all deleted afterwards with `engram delete
prompt` (matched by the content pattern `probe-%reply with the single word
OK.`).

## `lh exec` isolation — observed vs `--help`

**Claude Code 2.1.316, 2026-11-01, subscription (OAuth) auth, profile
`claude-lazy`.** Question: does `--setting-sources ""` — the evaluator's
isolation flag — silence the hooks behind `lh exec` while keeping what it
needs: the transcript under the pinned `--session-id` (timeout pricing,
ADR-038) and the `--workload` attribution (ADR-037). Its companion
`--no-session-persistence` is ruled out by construction: it removes that
transcript.

**Pollution before the change, read-only.** The key is a transcript whose
`entrypoint` is `sdk-cli` and whose first user message is not the evaluator
prompt, matched by session id against Engram `user_prompts`, queue task files
and knowledge-store session notes; frequency comes from `launches.entry =
'exec'`.

| Host | `lh exec` launches | Non-evaluator `sdk-cli` transcripts | Engram prompts | Queue tasks | Exported notes |
| --- | --- | --- | --- | --- | --- |
| agents CT (0.91.1) | 257 (2026-09-20 → 2026-11-01), driven by the lazy-vault timers | 198 (185 with cwd `LazyMind`) | 169 of 289 in its Engram | 84 of 111 | 11 |
| Mac | 52 (last 2026-09-30) | 128 (mostly e2e and probe cwds, not lazy-vault) | 99 | 20 of 1,212 | 3 |

**Method.** One `lh exec --profile claude-lazy --tier fast --workload
probe-exec-isolation` run per row from the worktree build, prompt
`probe-exec-<label>-<uuid> …` on stdin, then 25 s for the async hooks.
Observed: the envelope; Engram rows starting with the marker; queue files naming
the session id; the transcript under `projects/` and its `hook_*` attachment
count; session notes carrying the marker; the `session_attribution` row.

| Run | Argv beyond the default | Envelope | Engram | Queued | Transcript (hook attachments) | Export | Attribution |
| --- | --- | --- | --- | --- | --- | --- | --- |
| a | none (`--no-tools`, the argv until this change) | `OK`, `cost_source: agent` | 1 | 1 (SessionEnd) | yes (7) | none | yes |
| b | `-- --setting-sources ""` | `OK`, `agent` | 0 | 0 | yes (0) | none | yes |
| c2 | b, `--allow-tools Bash`, killed at `--timeout 30` during `sleep 60` | exit 124, `cost_source: transcript` | 0 | 0 | yes (0) | none | yes |
| d | b, cwd `LazyMind`, `--allow-tools Read,Glob,Grep`, read one note | first line verbatim, `agent` | 0 | 0 | yes (0) | none | yes |
| e | b, `--allow-tools Bash`, plus `--settings` with a `PreToolUse` hook touching a marker | `DONE` | 0 | 0 | yes (0) | — | — |
| f | none — the shipped `headless_argv` | `OK`, `agent` | 0 | 0 | yes (0) | none | yes |
| g | `-- --setting-sources user,project,local` | `OK`, `agent` | 1 | 1 | yes (7) | — | — |

**Observed vs help and spec.**

- `--setting-sources ""` silences the settings and the plugin hooks of a
  `lh exec` run as it does the evaluator's (b, f), and leaves the transcript
  under the pinned id: a run killed mid-tool is still priced from it (c2), and
  attribution is recorded before the spawn, unaffected.
- Run a's `SessionEnd` task was dropped by the worker (`80 user chars (min
  200)`), yet it rewrote the project's `handoff.md` with a slim snapshot of the
  probe session; run g did the same. Every queued headless task can overwrite
  the handoff the next real session loads.
- `--allowedTools` grants work with no settings loaded (c2 ran `Bash`, d ran
  `Read`), so a caller that names its tools — lazy-vault does on every call —
  loses nothing it asked for.
- **What isolation drops.** The profile's `permissions` (111 allow, 12 ask
  rules on `claude-lazy`), its `env` block, its default `model` and the
  plugins — and its own `PreToolUse` guards, `pre-tool-use-security` and
  `pre-tool-use-git-scope`, both `onFailure: block`. A run granted `Bash`,
  `Write` or `Edit` ran them unguarded. *Superseded the same day: the guards
  are re-injected (runs i, i2 below).*
- **MCP servers are dropped too.** Run a's transcript names the user-scope
  servers (`qmd`, `graphify`, `engram`), the plugin's and the claude.ai
  connectors' tools (`grep -c mcp__`: 6); run b's names none (0), and its
  `mcp_instructions_delta` attachment is gone. A caller granting an MCP tool
  through `--allow-tools` would find it absent.
- `--settings` survives `--setting-sources ""` (e): a hook passed as flag
  settings fired. *That path is now built: see runs i, i2.*
- The last `--setting-sources` wins (g): a caller forwarding
  `-- --setting-sources user,project,local` gets the profile back, hooks
  included.
- Run b cost USD 0.0015 against run a's USD 0.0092 for the same reply: the
  isolated run loads no plugin, skill or hook context.

**Guard re-injection (runs i, i2), same day, same build plus the change.**
`lh exec` now appends `--settings '{"hooks":{"PreToolUse":[…]}}'`, generated
from the entries deploy installs for the profile. The dry run's groups for
`claude-lazy` matched the deployed `settings.json` `PreToolUse` groups one for
one (six: five `lh hook … --profile claude-lazy`, security and git-scope with
`onFailure: block`, plus the config's `graphify hook-guard read`); the two
foreign moshi groups, written into `settings.json` by another tool, are not
re-injected. Both runs: `--profile claude-lazy --allow-tools Bash --tier fast
--workload probe-exec-guards`, cwd a scratch directory holding
`doomed-probe-exec-guards/keep.txt`, prompt on stdin from a file.

| Run | Asked to run | Envelope | `hooks.log` | Directory | Engram | Queued | Transcript (hook attachments) | Export | Attribution |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| i | `rm -rf ./doomed-probe-exec-guards` | `BLOCKED …`, `cost_source: agent` | 1 line: `pre-tool-use-security: blocked filesystem: rm -rf ./doomed-probe-exec-guards` | intact | 0 | 0 | yes (0) | none | yes |
| i2 | `ls ./doomed-probe-exec-guards` | `RAN keep.txt`, `agent` | 0 new lines | intact | 0 | 0 | yes (0) | none | yes |

- The guard runs, not merely registers: i's transcript carries the agent-side
  `PreToolUse:Bash hook error: [lh hook pre-tool-use-security --profile
  claude-lazy]: Blocked by lazy-harness PreToolUse: Recursive delete`, and
  the command never executed.
- Re-injecting `PreToolUse` brings back no session hook: Engram stayed at
  11,514 prompts, the queue at 398 done and 0 pending, the knowledge store at
  9 session notes, and i's transcript has no `hook_*` attachment.
- An allowed command still runs (i2): the guards add no refusal of their own.

**What was not measured.** A full lazy-vault command under the new argv (d is
one read-only call shaped like one); whether `.claude/rules/` in a project
still loads; managed-policy hooks. The `env`, `model` and `permissions` losses
follow from no settings file being read and were not probed one by one. One
sample per row. Runs a and g each left one Engram row, deleted afterwards with
`engram delete prompt` (#11504, #11509); both rewrote
`lazy-knowledge/memory/github.com/lazynet/lazy-harness/handoff.md`, left as
written.

## Hook `onFailure` — observed vs changelog

**Claim (2.1.295 changelog).** `onFailure: "block"` on a command hook blocks the
action when the hook "can't start, times out, or exits with an unexpected code".

**Probe, 2026-10-09, Claude Code 2.1.295 on macOS.** One `PreToolUse` `Bash`
handler per run, passed with `--settings`, `claude -p --model haiku` asked to
run `touch marker`; whether `marker` exists is the verdict.

| Handler | `onFailure` | `marker` |
|---|---|---|
| `exit 1` | absent | created — the action passes |
| `exit 1` | `block` | absent |
| `/nonexistent/lh-probe` | `block` | absent |
| `sleep 20`, `timeout: 3` | `block` | absent |
| `exit 0` | `block` | created |

**Probe, same day, Claude Code 2.1.283 on the agents CT** — a version that
predates the key. The handler `touch hook-ran` with `onFailure: "block"`, once
via `--settings` and once as a project `.claude/settings.json`: both times the
hook ran and `marker` was created. The unknown key is ignored and the settings
file still loads, unlike `"attribution": false`, which the 2.1.281 changelog
says older versions answer by skipping the whole file.

**What was not measured.** Exit 2 with `onFailure` set (the documented block
path, unchanged); HTTP hooks; events other than `PreToolUse`.
