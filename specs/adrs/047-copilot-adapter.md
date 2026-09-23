# ADR-047: `CopilotAdapter` — the run-backed subset, and the probe that owns the rest

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent adapter pattern), ADR-041 (multi-agent hook contract), ADR-042 (multi-file config planning), ADR-043 (system docs by role), ADR-044 (Codex's native edit path), ADR-045 (the credential boundary)

## Context

Step 11 of the multi-agent design is the third adapter, and it is the first one
whose evidence is **incomplete by construction**. `CodexAdapter` shipped after
six probes against `codex-cli 0.154.0` had settled its payload schema, its edit
dialect and its trust keying (ADR-044, `specs/designs/codex-evidence.md`).
Nothing equivalent exists for Copilot: this repo's own gate says *for an adapter
over an external binary the probes come first*, and here they have not run.

What **has** been established, by driving `copilot 1.0.83` rather than by
reading its bundle:

- `COPILOT_HOME` is honoured end to end, and auth survives a throwaway one.
- The hook event vocabulary is **eleven camelCase names, enumerated by
  rejection** — sixteen candidates written into a hook file, the binary read
  back for which it dropped. Five were dropped, and three of those
  (`userPromptSubmit`, `postCompact`, `stop`) are events this repo's builtins
  are written against.
- `$COPILOT_HOME/hooks/*.json` registers and fires.
- The `preToolUse` payload is `{sessionId, timestamp, cwd, toolName, toolArgs}`
  — camelCase, with `toolArgs` a nested JSON object rather than the
  JSON-encoded string the documentation claimed, and with **no** event-name
  field and **no** transcript path.
- A `deny` verdict is honoured **top-level and unwrapped**; the same verdict
  inside `hookSpecificOutput` is read, logged and ignored. Established with four
  envelopes varied against a control, after two earlier passes had each run one
  envelope and generalised from it.
- Copilot fails **closed** on a nonzero hook exit and **open** on a hook
  timeout.
- Tool names are lowercase and **unnormalised**: a real session used `bash`,
  `view`, `web_fetch`, `rg`, `web_search`, `task`, `skill`, `glob`. Codex
  rewrites `exec_command` to `Bash` before the payload is written; Copilot does
  not, so the name mapping is a real translation here and an identity there.

What has **not** been established, and the list is long enough to be the shape
of the decision rather than a footnote: the argument key `view` carries; whether
Copilot has an edit tool at all, let alone its name or arguments; whether
`additionalContext` is read on this path; the hook document's own schema;
whether `copilot-instructions.md` is loaded; whether `mcp-config.json` is read.
Each is a row in `specs/designs/copilot-evidence.md` with an empty `Observado`
cell and a numbered probe against it.

**One correction to the design fell out of writing that file.** Its line 1285
still reads *"Still unobserved: `~/.copilot/hooks/` exists and remains empty …
No hook has fired on either agent"* — contradicted three times inside the same
document, at `:1201`, `:2071-2098` and `:2135-2160`. It is the failure the
design names two paragraphs above itself: a provenance label ageing while the
prose around it moves on. The design is another lane's file and is not edited
here; the correction is recorded in the evidence file and in this ADR.

## Decision

### 1. The adapter encodes `run` and `log` rows only

Every mapping, verdict and path in `src/lazy_harness/agents/copilot.py` is
pinned to a line the design records as observed behaviour. A string in the
vendor artifact, a type in the shipped SDK and a page of vendor documentation
are all evidence that a *name exists* and nothing about whether it is live —
which is the gate the 1.0.40 hook-event list already failed once, surviving
three revisions because each cited the last rather than the binary.

So the module declares nothing for a `src` row, and the test file asserts the
absence rather than leaving it implicit. `test_no_tool_maps_to_modify_file_...`
and `test_additional_context_is_dropped_...` exist so that the day a probe lands,
a test fails and forces the ADR open.

### 2. Eleven events mapped, three canonical events absent

`hook_events()` maps all eleven accepted names. Four canonical names are new —
`post_tool_use_failure`, `pre_mcp_tool_call`, `subagent_start`, `subagent_stop` —
because `hook_events()` is the only mapping in the system and an accepted event
left out of it is unreachable forever. No builtin declares them, so they deploy
nothing today.

`session_stop`, `post_compact` and `user_prompt_submit` are **absent keys**, not
empty ones. The contract reads an absent key as "not delivered at all", which is
the distinction `lh doctor` needs: `stop_verify_guard` on Codex installs, runs,
finds no goal marker and passes; on Copilot nothing installs, because `stop`
never survives config load. One waits on a transcript reader, the other on the
agent's event vocabulary.

### 3. `DENY` on `preToolUse`, top-level, and nothing else anywhere

`format_hook_output` emits `{"permissionDecision": "deny",
"permissionDecisionReason": …}` on stdout with exit 0, and raises `ValueError`
for any other verdict on any event. `ALLOW` and `ASK` are in the SDK's output
union and have never been observed honoured; `BLOCK` has no home at all, since
`agentStop` — the only event whose SDK output declares `decision: "block"` — is
not one of the eleven the loader accepts.

Exit 2 with the reason on stderr is Copilot's second refusal route and is not
taken. One decision travels on one channel, and the one chosen is the one whose
reason text Copilot was seen to echo back.

### 4. `additionalContext` is not emitted

It is named in the 1.0.40 bundle and declared on four SDK output types — both
`src`. No run has shown the declarative hook path reading it. Emitting it would
hand every context-injecting builtin a channel nothing has shown the agent
reads, which is the same reason `CodexAdapter` emits no `systemMessage`.

This is the widest-blast-radius decision in the ADR and the cost is real: it is
listed in Consequences, not buried in a docstring. Probe 2 closes it.

### 5. Ownership is the filename, not a stamp

Copilot loads `$COPILOT_HOME/hooks/*.json` — a **glob**. So the harness takes one
path, `hooks/lazy-harness.json`, writes it wholesale, and leaves every sibling to
the user; a retirement keys on the path rather than on a marker parsed back out
of the document.

`CodexAdapter` needs its `description` stamp because Codex loads one fixed
`hooks.json` shared with the user. Copilot's glob removes that problem instead
of solving it — which matters here specifically, because whether this document
tolerates an unknown top-level key at all has never been measured.

### 6. The document shape is written from `src` and marked unverified

`plan_config` writes `{"version": 1, "hooks": {"<nativeName>": [{"command": …}]}}`.
`version: Required` and `version: Invalid literal value, expected 1` are strings
in the declarative hook loader's own region of `prebuilds/darwin-arm64/runtime.node`;
the array nesting under an event key is `run` (a real load produced
`hooks.preToolUse[0]._vsCodeCompat: Expected string`); the flat `command` key
comes from `Specify either 'exec' … or 'bash'/'powershell'/'command' … but not
both`, also a string.

**This is the one place the adapter ships a shape it cannot verify**, and it
ships it because an adapter that plans no config is not an adapter. Phase 0 of
`specs/gates/probes/copilot-probe1.sh` exists to fail it loudly: it writes five
candidate documents into five disposable homes and reports which load *and*
fire, and it refuses to run the later phases if none does.

### 7. MCP servers are not placed

`plan_config` ignores `servers`. `~/.copilot/mcp-config.json` is marked *present
on disk* in the design, and the 2026-09-14 sweep left it there deliberately: a
path that exists is not a path the binary was seen to read. It is also a file
Copilot writes itself, beside `permissions-config.json`, whose
`locations.<abs path>.tool_approvals[]` is every permission the user has granted
and is not reconstructible.

### 8. `credentials_file()` is `None`, and the reason is stronger than Codex's

ADR-045 reserves `None` for "the harness cannot speak for this agent's login".
`CodexAdapter` answers it on the weak ground of a file nobody opened. Here the
negative was measured: every deny-matrix run used a throwaway `COPILOT_HOME` and
auth survived it, so the credential is not under the config dir at all.

### 9. `system_docs()` returns one destination, and it is not a repo filename

`[Path("copilot-instructions.md")]`. This is the case ADR-043 was written for:
`AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and `.github/copilot-instructions.md` are
**repository-discovered** by Copilot and are not user-level destinations, so
writing one into a config dir installs nothing.

`instructions/**/*.instructions.md` is the second claimed destination and is not
returned. It is a glob rather than a path, and `system_docs()` asserts the agent
loads every entry it returns — two entries would be a stacking claim nothing has
measured. Probe 6 settles it.

### 10. No `TranscriptReader`, no `HeadlessAgent`

The reader is step 12's, and the design pins its method: Copilot's is
*generated* from `schemas/session-events.schema.json`, shipped beside the binary,
rather than reverse-engineered from event samples. `HeadlessAgent` is unclaimed
for `CodexAdapter`'s reason — `copilot -p` is known to start a run, and nothing
here has parsed its output.

## Evolution — 2026-09-19: lifecycle ownership uses two native artifacts

Decision 5's single reserved file remains the managed-builtin artifact, but it
cannot also carry ensure-present declarations: replacing or retiring that file
would delete entries whose omission grants no deletion authority. Copilot's
measured `hooks/*.json` glob provides a schema-compatible ownership boundary,
so the adapter now uses two ordinary version-1 hook documents:
`hooks/lazy-harness.json` for replaceable builtins and
`hooks/lazy-harness-external.json` for external and user-script declarations.

The external artifact is merged by native event, matcher and command identity.
Equivalent richer installed entries satisfy a declaration without losing
metadata, duplicates remain distinct, and later omission leaves the artifact
untouched. Both paths come from `config_targets()`, so deploy snapshots and
rollback include the added target without a second static path list.

The first plan after this split also reads the former combined artifact before
replacing or retiring it. Only an exact registry-backed builtin invocation on
its matching native event and matcher is classified as managed. Every unknown,
external or user-script group moves intact to the external artifact, including
native metadata and duplicates; an equivalent desired declaration adds no
second execution. Both writes are returned in one plan, and an invalid legacy
document refuses the plan rather than authorizing deletion. This migration is
derived from the harness registry and native group identity, without naming a
third-party integration.

## Consequences

**Every edit-gating builtin is inert on Copilot, and it is an absence rather
than a gap.** `post-tool-use-format`, `post-tool-use-sync-claude`,
`post-tool-use-ansible-lint` and `pre-tool-use-memory-size` gate on
`Operation.MODIFY_FILE` or on `tool.edits`, and `_TOOL_OPERATIONS` maps no tool
to either. That is not a mapping this adapter forgot: Copilot has never been
observed editing a file, in a run or in a log. Until probe 1 forces one, a
Copilot profile has no edit guards at all, and nothing downstream should read
the deploy's green output as saying otherwise.

> **Evolution (2026-09-16).** `post-tool-use-sync-claude` is `post-tool-use-sync-system-doc` since #366 (`4309633`, 2026-09-16).

**`pre-tool-use-read-size` deploys, runs, exits 0 and guards nothing.** `view`
maps to `READ_FILE` and `reads` stays `()`, because the argument key that
carries the path is unmeasured. This is ADR-044's own finding restated for a
second agent: a mapping without a structure revives nothing, and the operation
gate is the first of two.

**`pre-tool-use-security` is live on the command half and only that half.**
`bash` carries real shell text under `toolArgs.command`, so the command denylist
works. Its `read_file` and `modify_file` arms are silent, for the two reasons
above. A guard live on one half of its denylist and silent on the other is a
known and separate problem — the F8 gate records the same split for Codex and
deliberately does not assert on it.

**Every context-injecting builtin is silent on Copilot.** With decision 4,
`HookDecision.additional_context` is dropped: `context-inject`, and anything
else whose only channel to the model is that key, produces no effect on a
Copilot profile. They will still deploy and still exit 0.

**Three canonical events have no Copilot counterpart, so the hooks written
against them install nothing.** `stop` (`stop_verify_guard`, `engram-persist`,
`session-export` and the compound loop's Stop-hook entry point), `postCompact`
(ADR-036 already removed that builtin) and `userPromptSubmit`. This is the
"event does not exist" half of the two-state non-support the design's decision 3
describes, and it is reported as an absent key rather than as an empty verdict
set.

**No transcript-dependent builtin can run on Copilot**, and `hook_events()`
cannot say so — that is decision 11's `signals()`, and the reader is step 12's.
`transcript_path` is `None` on every event, so a hook cannot even be driven from
the payload the way Codex's can.

**A hook's timeout is a security parameter on Copilot, not a convenience.** It
fails **open** on timeout: a hook that sleeps past its budget is abandoned and
the command executes. `plan_config` writes no `timeoutSec`, so the vendor
default applies and that default is unmeasured. A deny-carrying hook is
therefore only as enforced as it is fast, and `lh doctor` does not report that
today.

**A deploy cannot tell that its hooks were dropped by policy.** The runtime
carries `Skipping repo/workspace hooks: blocked by enterprise customization
lockdown (strictPluginOnlyCustomization locks "hooks")` and a `disabledHooks`
key. Recorded so a future "deployed but never fires" report has a first suspect.

**MCP servers configured for a Copilot profile are silently not deployed**
(decision 7). `lh deploy` writes no MCP document and says nothing about it.

**Evolution (2026-09-18):** this gap is now visible in `lh doctor` under **MCP servers** and in the per-profile `lh deploy` output.

**The F8 translation gate does not cover Copilot and was not extended.** Its
agent list is a shell literal (`claude-code codex codex-blobless`) and
`specs/gates/f8/translate.py` imports exactly two adapters; the expected
inert/live sets are Codex's, derived from Codex's dialect. Adding a third leg
means editing a gate this lane does not own. The gate was run as a regression to
confirm registering a third adapter does not disturb it — that is all it says.

## Alternatives considered

**Wait for the probes and ship nothing.** The honest ordering, and it was
rejected on a specific cost rather than on schedule: the probe script has to be
written against *something*, and the thing it is written against is a hook
document shape and a payload reader. Building those as a probe and then again as
an adapter writes the same guesses twice and leaves the second copy untested.
Shipping the adapter makes the probe a test of the shipped code rather than of a
scratch file.

**Ship from the `source` rows too — map `apply_patch`, emit
`additionalContext`, return both system-doc destinations.** Rejected because it
is exactly the failure mode the design documents twice over: the 1.0.40 event
list and the withdrawn "compat mode maps tool names" claim were both names read
out of a bundle and reported as behaviour. A wrong mapping does not fail loudly
— it produces a hook that deploys, runs, exits 0 and guards nothing, which is
indistinguishable from a working one at every surface the harness has.

**Generate the whole adapter from `schemas/session-events.schema.json`.** The
schema is 783 KB, pinned to the version, and machine-readable — genuinely
attractive, and it is what step 12 does for the *transcript reader*. It does not
answer this step's questions: it declares session **event** shapes, and the hook
wire, the hook document schema and the verdict envelope are not in it. Using it
here would produce a generated adapter whose generated parts are the ones
already measured.

**Extend the F8 gate to a third leg in this lane.** Rejected on ownership and on
usefulness: the gate's value is the discrimination between a mapping fix and a
structural fix, and with no Copilot edit tool known there is no structure to
discriminate yet. It becomes worth doing the day probe 1 names an edit tool.
