# Claude Code dialect evidence — caller identification marker

**Status:** two probes recorded — 2026-09-24 against Claude Code 2.1.281, and
2026-09-29 against 2.1.284 (§ Headless isolation flags).
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
(ADR-039 F7). The probe sessions themselves left a `session_closed` row and a
queued task for each hooked run, which the worker skips as non-interactive.

