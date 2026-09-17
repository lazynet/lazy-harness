# ADR-056: Codex honours Claude-shaped `PreToolUse` matchers, and the deployed groups stay agent-agnostic

**Status:** accepted
**Date:** 2026-09-17
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent adapter pattern), ADR-032 (agent adapter completeness — the L3 path resolution this ADR's probe fell over), ADR-041 (multi-agent hook contract — which verdicts Codex honours), ADR-044 (Codex native edit path)

## Context

The F9 acceptance run of 2026-09-17 12:32 reported all 31 hooks approved and
still failed three assertions: a `rm -rf` executed and a `.env` was modified,
both under a profile whose `pre-tool-use-security` group was deployed and
trusted. Reading the code could not tell a suppressed matcher from a hook that
fired and allowed, and both readings produce the same file state.

Every `PreToolUse` group the harness deploys carries a matcher literal written
for Claude Code's tool vocabulary. `pre-tool-use-security` carries
`Bash|Read|Edit|Write|NotebookEdit` (`hooks/loader.py`), and that literal names
five Claude Code tools, none of which is a Codex tool name — Codex's native edit
tool is `apply_patch` (ADR-044). `_hook_groups`'s own docstring already recorded
that a matcher matching no tool "suppressed the hook completely and silently",
which made a suppressed group the leading hypothesis for the 12:32 failure.

Three probes were run from an Aqua terminal against `codex-cli 0.154.0`, model
`gpt-6-astra`, before anything was decided.

### The matcher probe (13:22) — how Codex evaluates a matcher

One throwaway `CODEX_HOME`, one `PreToolUse` group per spelling, two turns — a
shell call and a native edit — with the matcher-less control rendered *last*, so
that a run in which nothing else fired could still distinguish first-match-wins
from every-other-matcher-failing.

| Matcher | `tool_name: Bash` | `tool_name: apply_patch` |
|---|---|---|
| `Bash\|Read\|Edit\|Write\|NotebookEdit` | fired | fired |
| `^Bash$` | fired | did not fire |
| `Edit\|Write` | did not fire | fired |
| (no `matcher` key) | fired | fired |

Four things follow, and none of them was on record before:

1. **The matcher is a regex, with working anchors.** `^Bash$` fired on `Bash`
   and not on `apply_patch`, so Codex is not doing substring or literal
   equality.
2. **Codex matches a tool's Claude-compatible alias as well as its native
   name.** `Edit|Write` fired on a call whose payload reports
   `tool_name: apply_patch`. The alias is not in the payload — the payload is
   the native name — so the aliasing happens inside Codex's matcher evaluation.
3. **Every group is evaluated, not just the first that matches.** The
   matcher-less control fired on both turns alongside the matching literals.
4. **The eight groups the harness deploys are not suppressed.** The hypothesis
   the probe was built to confirm is false.

### The hook-exec probe (14:34) — whether the deployed command runs

With the matcher question closed, four candidates were left for the 12:32
failure: (a) the bare name `lh` does not resolve in the environment Codex spawns
a hook into, (b) the hook runs, crashes and exits 0, (c) the payload differs from
the shape §1 of `codex-evidence.md` records, (d) Codex ignores a valid deny under
`exec`. Five groups — three that capture and swallow stdout, two that answer
Codex, one bare-name and one absolute-path each — separated them on one turn.

**All four are falsified.** Every group recorded exit 0 and a valid envelope with
`permissionDecision: "deny"`; `command -v lh` inside the hook process resolved to
the installed binary on both the bare and the absolute spelling; the payload
carried `hook_event_name`, `tool_name`, `tool_input.command`, `session_id`,
`turn_id`, `transcript_path`, `cwd`, `model`, `permission_mode` and
`tool_use_id`, matching §1; and the fixture directory survived.

**And the verdict surfaces in Codex's approval-review stage.** `stream.stderr`
line 1 is
`ERROR codex_core::tools::router: error=Command blocked by PreToolUse hook: Blocked by lazy-harness PreToolUse: Recursive delete (filesystem).`
while the `--json` stream carries only the model's prose about it —
`"Automatic approval review blocked \`rm -rf -- doomed\` because recursive
filesystem deletion is disallowed. The directory was not deleted."` A consumer
looking for the harness's own refusal must read stderr; the JSON stream reports
the model's account of it, not the mechanism.

### What the probe's own summary said, and why it is not evidence

The 14:34 summary contradicted all of the above. Three reporting bugs, each in a
reader rather than in what was written: an in-process control invoked without
`LH_CONFIG_DIR`, so it asked the machine's real config about a throwaway profile
and printed a banner telling the reader to discard a correct run; a block-line
check grepping `stream.jsonl` for a line Codex writes to stderr; and a hook-log
check reading the profile's `config_dir` for a line that `agent_runtime_dir`
(ADR-032 L3) puts under `CODEX_HOME`, which the probe then deleted on exit.
They are fixed, with tests in both directions, in the commit that adds this ADR.
The records were right at 14:34; only the summary was wrong.

## Decision

### 1. The deployed groups keep their Claude-shaped matchers

No adapter emits a Codex-specific matcher, and `_hook_groups` continues to pass
`entry.matcher` through unchanged.

The matcher is a property of the *builtin*, declared once on `BuiltinHookSpec`
in `hooks/loader.py` and shared by every agent that deploys that builtin. It
says which tool calls the hook is about, in the vocabulary the harness already
speaks. Per-agent matchers would mean forking that registry per adapter — a
second literal per builtin per agent, each one a thing to keep in step with the
first, to express a scoping decision that does not vary by agent.

The probe removes the reason to pay that. Codex matches
`Bash|Read|Edit|Write|NotebookEdit` on both of its tool paths, so the literal
already covers the calls the guard is meant to see. Should a future Codex drop
the alias, the failure is a suppressed group — which is now a *measured*
signature (`never invoked` under `LH_HOOK_TRACE`, §4 of `codex-evidence.md`)
rather than an unattributable silence.

### 2. `#382` changed no deployed group, and this ADR says so

`b971a9b`'s subject reads "Codex hook groups carry matchers Codex can match".
That describes what the probe *measured*, not a change the commit made: its diff
touches probes, the gate, `hooks/runner.py` and tests, and no adapter,
`deploy/engine.py` or `hooks/loader.py`. The matcher literal it refers to has
been in `loader.py` since `8959e52`, long before it.

What `#382` did ship for the deployed path is `LH_HOOK_TRACE` — one line per
dispatch, written at the single dispatch point in `hooks/runner.py`, off unless
the variable is exactly `"1"`. It exists because every `pre_tool_use` builtin
logs only when it has something to say, so a hook that fired and *allowed*
leaves nothing behind, and the gate could not tell that from a group the agent
never consulted. The two have opposite fixes.

### 3. The trace lands under the agent's runtime dir, and prose says which

`agent_runtime_dir` resolves the adapter's own env var before the profile's
`config_dir` (ADR-032 L3). Every hook Codex spawns inherits `CODEX_HOME`, so
under Codex the trace line is in `$CODEX_HOME/logs/hooks.log` and the profile's
`config_dir` stays empty. That precedence is kept — the env var is the agent's
own statement of where its home is — and every document that names the
destination names that one.

## Consequences

**The F9 12:32 failure is not a matcher, a PATH, a crash, a payload or an
ignored verdict.** All five are falsified by measurement. What separates the
12:32 run from the 14:34 probe is down to three deltas — the deployed
`hooks.json` (8 real groups, including `moshi` and `graphify hook-guard`, against
5 hand-rendered ones), the trust store (31 TUI-approved `hooks.state.` entries
against `--dangerously-bypass-hook-trust`), and the driver (the F9 live path
against `codex exec`). `specs/gates/probes/codex-hook-probe6.sh` is designed to
separate them and has not been run.

Two readings of the deployed profile narrow it further, and both were taken
without spending a turn. `~/.codex-lazy/logs/hooks.log` carries
`session-context: fired` and `compound-loop: fired` timestamped 12:32:53-12:32:58,
so the 12:32 run did reach the deployed home and its matcher-less groups did fire
— **the home is not the delta**, and `pre-tool-use-security` wrote nothing that
run with no `LH_HOOK_TRACE` yet to say why. And in the deployed `hooks.json`
`pre-tool-use-security` is **group index 0**, with a `trusted_hash` stored under
`hooks.state."…:pre_tool_use:0:0"` — so neither "an earlier group ended the
dispatch" nor "the group has no approval" is available as an explanation. What
arm B can still find is a stored hash that no longer matches the group as
deployed, which `codex_trust.py` declines to recompute and only a re-approval can
settle.

**A gate reading the trace must read the agent's runtime dir.** The F9 gate now
pins `CODEX_HOME` on the turns it drives and on its trace self-test, so what is
driven, what writes the log and what is read are one directory by construction.
Before, they agreed only because the machine that ran it had the variable unset.

**A probe is not evidence until its reader is exercised in both directions.**
Three of the 14:34 summary's four readings were wrong and all four were stated
with the same confidence. The repo's existing gate covers this — an artifact is
verified by the system that consumes it, a gate script in both directions — and
it was not applied to a script whose only consumer was a human reading its
stdout. It is now: the probe's summary has tests that feed it a run that blocked
and a run that did not.

**A commit subject is not a changelog.** `#382`'s subject named a behaviour it
measured as though it were a change it made, and the `(ADR-056)` it cited did not
exist in the tree for the ADR to correct the record. Both are closed here.
