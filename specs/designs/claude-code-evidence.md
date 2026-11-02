# Claude Code dialect evidence — caller identification marker

**Status:** two probes recorded — 2026-09-24 against Claude Code 2.1.281, and
2026-09-29 against 2.1.284 (§ Headless isolation flags), 2026-10-09 against
2.1.295 and 2.1.283 (§ Hook `onFailure`), and 2026-11-01 against 2.1.316
(§ Evaluator isolation, § Evaluator JSON result envelope).
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
  implemented*). *Resolved the same day: § Evaluator JSON result envelope.*

**What was not measured.** A real evaluator prompt under the shipped flags
(JSON parse rate, grade yield); managed-policy hooks, which this host does not
have; the second `claude -p` argv, `ClaudeCodeAdapter.headless_argv`, behind
`lh exec`, which is unchanged and still boots the profile. One sample per flag
set; two extra baseline runs came from debugging the probe script, so the
probe left three Engram rows, all deleted afterwards with `engram delete
prompt` (matched by the content pattern `probe-%reply with the single word
OK.`).

## Evaluator JSON result envelope — observed vs spec

**Claude Code 2.1.316, 2026-11-01, subscription (OAuth) auth.** Question: does
`--output-format json` under the isolation flags above carry the usage that
`--no-session-persistence` took away with the transcript, without bringing the
transcript, a hook, or an Engram row back.

**Method.** `claude -p --model M --output-format json --setting-sources ""
--no-session-persistence`, `CLAUDE_CONFIG_DIR=~/.claude-lazy`, from an empty
scratch directory. Prompt `probe-usage-7f3a: reply with the single word OK.`
(runs i, j) and a `build_prompt` evaluator prompt marked `probe-usage-e2e-9c1d`
sent through `run_inference(role="distill")` with an isolated `LH_CONFIG_DIR`
and scratch `metrics.db` (run k). After each run: `find` for the session id
under `~/.claude-lazy` and `~/.claude`, Engram `user_prompts` matching
`%probe-usage%`. Run i's stdout is the fixture
`tests/fixtures/claude-p-json-result.json`.

| Run | Model | Exit | `result` | `session_id` | `total_cost_usd` | Harness price | Transcript | Engram |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| i | `claude-haiku-4-5-20251001` | 0 | `OK` | `bbe45a2d…` | 0.0185705 | 0.0185705 | none | 0 |
| j | `claude-haiku-5-5` | 0 | `OK` | `170ab1b5…` | 0.00119655 | 0.00119655 | none | 0 |
| k | `claude-haiku-5-5` (evaluator prompt) | 0 | JSON, `parse_response` OK, 7 keys | `9015bf96…` | — | 0.00184765 | none | 0 |

**Observed vs spec.**

- The envelope is `type: "result"` with `result` (the model's text),
  `is_error`, `subtype`, `session_id`, `total_cost_usd`, `usage` (snake_case,
  last turn, with `service_tier` and `cache_creation.ephemeral_{5m,1h}_input_tokens`)
  and `modelUsage` (camelCase, **per model**, with
  `cacheCreationEphemeral5mInputTokens`, `cacheCreationEphemeral1hInputTokens`
  and `costUSD`). `ClaudeBackend` reads `modelUsage`, because one call can bill
  more than one model and `session_stats` is keyed `(session, model)`.
- `session_id` is present although `--no-session-persistence` writes no file
  under it: an id for the call, not for a transcript. It keys the row.
- The harness pricing table agrees with `costUSD` to the last digit on both
  models (runs i, j), so the stored row uses the harness price, the same
  function the ingest uses, and `costUSD` is kept on `ModelUsage` only.
- An error with exit 0 (`is_error: true`) is not observed here; the parser
  treats it as `LLMBackendError` rather than return the error text as an
  evaluation, since `result` would otherwise reach `parse_response`.
- Run k's row: `profile=claude-lazy`, `workload=inference:distill`,
  `agent=claude`, `billing_model=flat_rate`, `billed_cost` null
  (`subscription`), `api_equivalent_cost` 0.00184765 `priced`.

**What was not measured.** An `is_error: true` envelope from a real failure;
a call billing two models; the remote sink path (run k configured
`sqlite_local` only).

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
