# Claude Code dialect evidence — caller identification marker

**Status:** three probes recorded — 2026-09-24 against Claude Code 2.1.281,
2026-09-29 against 2.1.284 (§ Headless isolation flags), and 2026-10-05 against
2.1.289 (§ Distill role — `rule_violations` schema probe).
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

## Distill role — rule_violations schema probe (2026-10-05)

**Claude Code 2.1.289, `distill` role → backend `claude`, model
`claude-haiku-4-5-20251001`, subscription auth.** Question: does the real
evaluator role return a parseable `rule_violations` array when the prompt
carries a `## Rules already in force (id — rule)` section, as
[the contract-aware evaluator design](2026-10-05-evaluator-contract-dedupe-design.md)
assumes? The design asked for this probe before any test or production code.

**Method.** One call through `run_inference(prompt, role="distill", cfg=cfg)`,
no retry. The prompt is the real `build_prompt` output for the fixture, with
three string splices and nothing else changed (`src/` untouched). The index was
built by a throwaway extractor: bullets and headings of the repository
contract, then of the profile contract, `id = "<source>:" + sha256(whitespace-
collapsed lowercase text)[:16]`, 6,000-character budget trimming the profile
first. Shortcuts: top-level bullets only, no nested list handling, tables and
fenced code skipped, no dedupe by `realpath`.

**Fixture.** One interactive session of this repository (15 messages, 6.8 KB of
extracted transcript) in which the evaluator had already recorded a
claims-without-evidence failure. Parsed through the real `extract_messages`.

**Spliced prompt delta** (59,536 → 65,845 characters, +6.3 KB):

```text
+ ... Do not duplicate rules already proposed or listed in the rejected section.
+   If the recurring root cause is covered by a rule listed under "Rules already
+   in force", emit a `rule_violations` entry citing its id instead of a
+   claude_md_proposals entry.
+ ## Rules already in force (id — rule)
+ - repo:4de339c123a65976 — **Worktrees for every code change.** Any edit ...
+ - repo:f6c0c2d0065b268a — **Strict TDD.** No production code without ...
+   ... 28 repository rules, 5,791 characters
+   "rule_violations": [{"rule_id": "id exactly as listed under Rules already in
+   force", "evidence": "one sentence from the transcript"}],
+ - rule_violations: rules from the Rules already in force section that this
+   session violated. Cite the id exactly as listed; never invent an id. Empty
+   list `[]` if none.
```

**Observed.** Exit success, 69.1 s, 2,133 characters, fenced in a ```` ```json ````
block. `parse_response` returned a dict with the keys `decisions`, `failures`,
`learnings`, `handoff`, `claude_md_proposals`, `rule_violations`, `grade`,
`goal_declared`, `project_update`. `rule_violations` is present and a `list`,
and it is empty (`"rule_violations": []`); so is `claude_md_proposals`. No id
was cited, so none was invented and none restated a rule.

**Observed vs design.**

- The schema addition parses through the unchanged parser, and the model neither
  dropped the key nor changed its type. That is the whole claim confirmed.
- **The 6,000-character budget did not hold the profile contract.** Both
  contracts yield 43 extracted rules each; the repository contract alone filled
  28 rules and 5,791 characters, leaving zero profile rules. Trimming the profile
  "first" trims it entirely, and the evidence-before-claims rule the fixture
  failure belongs to lives in the profile contract. The design's premise that the
  budget keeps both sources is false for these two files.
- The repository rules that were kept include a close match for the fixture's
  failure (`A tool's exit code is not proof of its effect`), and the model still
  cited nothing: with an `[EVITAR]` trigger that requires the same root cause
  2+ times, a single-session failure does not reach the new branch.
- The evaluator's view of the transcript (`extract_messages`) carries no tool
  calls, so the model graded the session as "narrated audit work without
  invoking any tools". The failure that selected this fixture may be an artifact
  of that view and not a violation.

**What was not measured.** Whether the model ever cites a valid id, or invents
one: a single call with an empty array exercises neither path, so the
invented-id validation stays unobserved by the real role. Run-to-run variance
(one sample). Prompt cost beyond the +6.3 KB, and any effect on grade or
handoff quality. Behaviour on a fixture whose violated rule sits inside the
index and whose root cause repeats 2+ times in the recorded failures.
