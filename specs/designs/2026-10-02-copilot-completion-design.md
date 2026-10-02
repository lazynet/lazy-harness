# Completing `CopilotAdapter`

Status: **proposed** (2026-10-02). Docs only: no code, test, ADR, backlog,
roadmap or `docs/` page is edited by this document; §7 lists the edits it
proposes elsewhere. Inputs: ADR-047, `specs/designs/copilot-evidence.md` as
updated with the `copilot 1.0.89` run of 2026-10-02, and the adapter at
`src/lazy_harness/agents/copilot.py`.

Citation convention. `copilot.py:N` is `src/lazy_harness/agents/copilot.py`;
`base.py:N` is `src/lazy_harness/agents/base.py`; `loader.py:N` is
`src/lazy_harness/hooks/loader.py`. An evidence row is cited as
`evidence §<section> <row>`, and a cell filled by the 2026-10-02 run carries
**run, 1.0.89, 2026-10-02** in the evidence file. Every identifier this
document introduces is marked *(proposed)*; every other identifier exists in the
code at the cited line.

## 1. Goal and non-goals

**Goal.** Make Copilot CLI a first-class provider: every capability the
`AgentAdapter` contract (`base.py:589`) and its optional protocols
(`HeadlessAgent`, `base.py:350`; `TranscriptReader`, `base.py:492`) describe is
either implemented against a measured row or refused with a named reason — the
same bar `ClaudeCodeAdapter` and `CodexAdapter` meet. The framework treats
Copilot as one more agent; nothing below depends on a particular installation,
profile layout or user.

ADR-047's rule stays the rule: **the adapter encodes `run` and `log` rows only**
(ADR-047 §1). Completion means moving rows from *probe* to *measured* and then
encoding them — never encoding a `src` row to close a gap faster.

**Non-goals.**

- Translating Claude Code's event vocabulary onto events Copilot does not have.
  `stop`, `postCompact` and `userPromptSubmit` stay absent keys
  (`copilot.py:87-89`, ADR-047 §2); nothing here invents a substitute.
- Writing into vendor-owned state: `permissions-config.json`, `settings.json`,
  `session-store.db` (`copilot.py:589-600`).
- Generating the adapter from `schemas/session-events.schema.json`. ADR-047
  rejected it for the hook surface; it remains the method for the transcript
  reader only (§2.13).
- Extending the F8 gate in the same change as the edit mapping (§5, D7).
- Any change to how other adapters behave, except where a shared docstring is
  wrong about Copilot (`base.py:151-153`, `base.py:209`).

## 2. Capabilities

Each subsection: **Now** (current code), **Evidence** (the row that decides it),
**Change** (proposed adapter change), **Effect on builtins**, **Tests** (written
first, failing, under strict TDD), **Probe still needed**.

### 2.1 Hook payload

**Now.** `parse_hook_input` reads `sessionId`, `cwd`, `toolName`, `toolArgs`
(`copilot.py:232-242`); `transcript_path`, `tool_use_id`, `tool_response` and
`source` are never set (`copilot.py:239`; defaults at `base.py:207-214`).

**Evidence.** evidence §1: `cwd` on all five events that fired, never
`workingDirectory`; no transcript path, no call id; `postToolUse` carries
`toolResult: {resultType, textResultForLlm}`; `sessionStart.source` = `new`;
`permissionRequest` carries `toolInput`, not `toolArgs`, with per-tool keys that
differ from `preToolUse` (`bash` → `{command}`, `edit` → `{file_path, diff}`);
`sessionEnd` carries `reason` = `complete`.

**Change.**

1. `postToolUse`: set `HookEvent.tool_response` to the `toolResult` mapping,
   untranslated, behind an `isinstance(dict)` guard. `base.py:208-211` already
   declares the field unconstrained for exactly this case; fix its docstring
   from `{result_type, ...}` to the observed `{resultType, ...}`.
2. `permissionRequest`: read the argument object from `toolInput` on that event
   only, through a per-event argument-key table `_ARGUMENT_KEYS` *(proposed)*
   rather than a fallback chain — a fallback would read `toolInput` on an event
   whose wire never carried it. Map `bash`'s `command` only; `edit`'s
   `{file_path, diff}` is a unified diff whose format is unmeasured, so
   `edits` stays `()` on this event.
3. `sessionStart.source`: **not mapped** in this design. No builtin reads
   `HookEvent.source` (grep of `src/lazy_harness/hooks/builtins/` finds no
   reader), and `new` → `startup` is a vocabulary translation with one observed
   value. See D5.
4. `cwd` stays `cwd`-only (`copilot.py:222-225`); the run confirmed the wire.

**Effect on builtins.** None become live: no builtin reads `tool_response`
(same grep) or `source`. Item 1 is correctness for future consumers and for
`raw`-free hooks; item 2 makes `permission_request` hooks see the command.

**Tests.** `test_post_tool_use_result_lands_in_tool_response` *(proposed)*:
payload with `toolResult` → `event.tool_response == {...}`; and with
`toolResult: null` / a list → `None`. `test_permission_request_reads_tool_input`
*(proposed)*: `toolInput.command` → `tool.command`; the same payload with
`toolArgs` instead → `command is None` (proves the key is per event, not a
fallback). Both watched failing with the mapping removed.

**Probe still needed.** P1-events (§3.2): the six unfired events' payloads,
`resume` source.

### 2.2 Edit gating — `MODIFY_FILE`

**Now.** No tool maps to `MODIFY_FILE` (`copilot.py:149-152`), pinned by
`test_no_tool_maps_to_modify_file_because_none_has_been_observed`
(`tests/unit/test_agent_copilot.py:252`). `COPILOT_TOOL_NAMES` lacks `edit`
(`copilot.py:129-131`).

**Evidence.** evidence §2 *The edit tool*: `edit`, `toolArgs = {path, old_str,
new_str}`, absolute path under `cwd`, file changed. *Multi-file edits*: one
path per call observed.

**Change.** Add `"edit": Operation.MODIFY_FILE` to `_TOOL_OPERATIONS`, add
`edit` to `COPILOT_TOOL_NAMES`, and fill `ToolCall.edits` in `_parse_tool`
(`copilot.py:245-265`) with one
`FileEdit(path=Path(path), replacements=((old_str, new_str),))`
(`base.py:129-144`), **only** when `path`, `old_str` and `new_str` are all
strings — the one shape the run recorded. Any other shape (a missing or `null`
`new_str`, a non-string `path`) yields `edits = ()` with `operation` still
`MODIFY_FILE`, so the call is visibly unprojected rather than guessed at. This
string guard is a new requirement: `ClaudeCodeAdapter`'s parser does not
implement it — it takes any truthy path and coerces it with `str()`
(`claude_code.py:685`, `:690`, `:695`) and reads a missing `new_string` as a
deletion (`claude_code.py:701-705`), a convention that cannot establish
Copilot's `new_str` semantics. Deletion semantics wait on P1-edit's deletion leg
(§3.2). `is_create` stays `False` — creation is unmeasured. The test at
`test_agent_copilot.py:252` is **inverted, not deleted**, so the absence of
other mappings stays asserted. Correct `base.py:151-153`, which still names
"Copilot's `edit`" as multi-file.

**Builtins gate on the native name, not only on the operation.** Four
edit-gating builtins check `tool.native_name in INSPECTED_TOOLS` after the
operation, and their set is `_shared.EDIT_TOOLS = {"Edit", "Write",
"apply_patch"}` (`hooks/builtins/_shared.py:42`): `post-tool-use-format`
(`post_tool_use_format.py:29`, `:39`), `post-tool-use-ansible-lint`
(`post_tool_use_ansible_lint.py:38`, `:118`), `pre-tool-use-memory-size`
(`pre_tool_use_memory_size.py:49`, `:259`). `memory-size` additionally projects
by name — `Write`, `apply_patch`, `Edit` (`pre_tool_use_memory_size.py:150`,
`:163`, `:166`) — so a Copilot `edit` falls through even past the gate. Only
`post-tool-use-sync-system-doc` gates on the operation alone at runtime
(`post_tool_use_sync_system_doc.py:104-110`), and `pre-tool-use-security`
dispatches on `Operation` (`pre_tool_use_security.py:622-659`).

So the adapter mapping alone is not enough. The builtin-side change *(proposed)*
follows the precedent `apply_patch` set when Codex's edit tool was added: add
`"edit"` to `EDIT_TOOLS`, and give `memory-size`'s projection an `edit` branch
over the same `FileEdit.replacements` shape `Edit` uses. The existing gate
`test_every_inspected_tool_name_is_one_some_agent_emits`
(`tests/unit/test_hook_matcher_coverage.py:179`) then requires `edit` in
`CopilotAdapter._TOOL_OPERATIONS`, and
`test_apply_patch_joins_inspected_tools_without_widening_claude_codes_matcher`
(`:196`) is the model for asserting Claude Code's matcher is not widened.

**Effect on builtins**, by what each still needs:

| Builtin | Adapter mapping | `EDIT_TOOLS` change | Matcher (§2.7) | Channel (§2.5) |
|---|---|---|---|---|
| `post-tool-use-sync-system-doc` | needed | not needed | none declared | none (side effect) |
| `post-tool-use-format` | needed | **needed** | none declared | none (side effect) |
| `pre-tool-use-security`, modify arm | needed | not needed | `loader.py:242` | `DENY` (emitted) |
| `post-tool-use-ansible-lint` | needed | **needed** | `loader.py:159` | `additional_context` on `postToolUse` (`post_tool_use_ansible_lint.py:136`) |
| `pre-tool-use-memory-size` | needed | **needed**, plus projection branch | `loader.py:222` | `system_message` on `preToolUse` (`pre_tool_use_memory_size.py:279`) |

"Needs a matcher" means: fires only if P4 shows the deployed Claude-spelled
matcher matches `edit`, or §2.7 rewrites/omits it. Activation is claimed only
after the hook's effect is observed on a Copilot run, not from the mapping.

`herdr-context-gauge` is **not** in this table: it declares no operations
(`loader.py:138-155`), and its `post_tool_use` placement requires
`Signal.TOKEN_USAGE` (`loader.py:152`), which deploy filters out on an agent
with no reader supplying it (`deploy/engine.py:458`; pinned by
`tests/unit/test_deploy_signal_filter.py:200-214`). It waits on a
`TOKEN_USAGE`-capable Copilot reader (§2.13), and only then on §2.7.

**Tests.** Adapter: `test_edit_maps_to_modify_file_with_one_replacement`
*(proposed)*; `test_edit_with_a_non_string_field_has_no_edits` *(proposed)*,
covering missing `path`, `null` `new_str` and a non-string `path`. Consumers,
each watched failing with `"edit"` removed from `EDIT_TOOLS`:
`test_format_runs_its_formatter_on_a_copilot_edit` *(proposed)*;
`test_memory_size_projects_a_copilot_edit` *(proposed)*;
`test_ansible_lint_inspects_a_copilot_edit` *(proposed)*;
`test_sync_system_doc_regenerates_on_a_copilot_edit` *(proposed)*.

**Probe still needed.** P1-edit (§3.2): deletion of text (does `edit` send an
empty, `null` or missing `new_str`?), file creation, replace-all, two files in
one request, and whether a separate create/write tool exists.

### 2.3 Read gating — `READ_FILE`

**Now.** `view` maps to `READ_FILE` with `reads = ()` (`copilot.py:140-152`), so
`pre-tool-use-read-size` deploys and guards nothing (ADR-047 Consequences).

**Evidence.** evidence §2 *`view` arguments*: `{path}`, absolute, under `cwd`.
No range key on a whole-file read.

**Change.** Fill `reads = (Path(path),)` when `path` is a non-empty string.
Leave `offset`/`limit` (`base.py:161-163`) `None` until a ranged read is
measured; a guard that sees no range assumes a whole-file read, which is the
conservative direction for a size guard.

**Effect on builtins.** `pre-tool-use-security`'s read arm becomes reachable
(subject to §2.7); it dispatches on `Operation` (`pre_tool_use_security.py:622-659`),
so filled `reads` change what it denies wherever the hook fires.
`pre-tool-use-read-size` stays inert for **three** reasons: it gates on
`INSPECTED_TOOLS = {"Read"}` (`pre_tool_use_read_size.py:21`, `:107`) — the
builtin-side change *(proposed)* is adding `"view"` there, as in §2.2; its
matcher is `Read` (`loader.py:232`, §2.7); and it speaks only through
`system_message` (`pre_tool_use_read_size.py:128`), which the adapter drops
(§2.5).

Doctor does **not** report this today and the mapping does not change what it
reports. The operation report computes `declared - producible`, where producible
is `_TOOL_OPERATIONS.values()` (`hooks/event_surface.py:70-83`, `:103`); `view`
already maps `READ_FILE` (`copilot.py:151`), so `READ_FILE` is reported as
producible now, with `reads = ()`. The renderer reports unmapped operations only
(`doctor_cmd.py:641-668`). A **structure** diagnostic — an operation mapped but
its arguments never projected — would be new; §2.15 proposes it.

**Tests.** `test_view_fills_reads_with_its_path` *(proposed)*;
`test_view_without_path_leaves_reads_empty` *(proposed)*;
`test_read_size_inspects_a_copilot_view` *(proposed, consumer, watched failing
with `"view"` removed from its `INSPECTED_TOOLS`)*; one F8-style test that
a `READ_FILE` call with a path makes `pre_tool_use_security` deny a denylisted
path through the Copilot parser (watched failing with `reads` emptied).

**Probe still needed.** P1-view-range (§3.2).

### 2.4 Verdict envelope, including `allow` / `ask`

**Now.** `DENY` on `pre_tool_use` only; any other verdict raises `ValueError`
(`copilot.py:289-303`, `:110-111`).

**Evidence.** evidence §3: `deny` re-measured on 1.0.89. `allow` → tool ran,
but under `--allow-all-tools`, so honoured-vs-ignored is undecidable. `ask` →
`Denied by preToolUse hook (unable to ask user for confirmation)` in `-p`.

**Change.** **None yet** for `ALLOW` and `ASK`. No builtin emits either:
`Verdict.ALLOW` appears in builtins only inside docstrings that forbid it
(`pre_tool_use_security.py:618`, `pre_tool_use_git_scope.py:406`), so adding
them unblocks nothing today and adds two channels to keep true. If P2-allow
(§3.2) shows `allow` overrides a would-be prompt, add `ALLOW`; if interactive
`ask` is shown to prompt, add `ASK` with the documented degradation (`ask` is a
deny in `-p`) recorded on `HookSupport`. See D4.

**Effect on builtins.** None today; `pre-tool-use-security` and
`pre-tool-use-git-scope` already express approval as abstention.

**Tests.** Unchanged pins: `ALLOW`/`ASK` still raise. When P2 lands, the pins
flip under the same test names.

**Probe still needed.** P2-allow, P2-ask-interactive (§3.2).

### 2.5 `additionalContext` and `systemMessage`

**Now.** Neither emitted (`copilot.py:284-298`); pinned by
`test_additional_context_is_dropped_because_no_run_has_shown_it_read`
(`test_agent_copilot.py:366`).

**Evidence.** evidence §3 *`additionalContext`* and *`systemMessage`…*: both
accepted without error on `preToolUse`; reach to the model **inconclusive**
(defect 3); `sessionStart` untested.

**Change.** **None until P2-context runs** with a non-echo design (§3.2). The
1.0.89 run moves this row from "never observed read" to "accepted, effect
unknown", which is not a licence to emit. When measured, emit per event, not
globally: the channel may be honoured on `sessionStart` and not on
`preToolUse` or `postToolUse`, or any other combination, and `HookSupport` has no per-event channel field
— so the gate lives in `format_hook_output` as a per-event table
`_CONTEXT_EVENTS` *(proposed)*.

**Effect on builtins.** Each is unblocked only by a positive result **on its own
event** — the per-event rule above:

| Builtin | Channel | Event | P2-context leg | Also needs |
|---|---|---|---|---|
| `context-inject` | `additional_context` + `system_message` (`context_inject.py:1038`) | `session_start` | `sessionStart` | — |
| `session-start-preflight` | `additional_context` (`session_start_preflight.py:305`) | `session_start` | `sessionStart` | — |
| `pre-tool-use-read-size` | `system_message` (`pre_tool_use_read_size.py:128`) | `pre_tool_use` | `preToolUse` | §2.3 name change, §2.7 |
| `pre-tool-use-memory-size` | `system_message` (`pre_tool_use_memory_size.py:279`) | `pre_tool_use` | `preToolUse` | §2.2 name change, §2.7 |
| `post-tool-use-ansible-lint` | `additional_context` (`post_tool_use_ansible_lint.py:136`) | `post_tool_use` (`loader.py:160`) | **`postToolUse`** | §2.2 name change, §2.7 |

`pre-tool-use-graph-assist` is scoped to `claude-code` (`loader.py:216`) and
stays out.

**Tests.** On a positive result: invert the pin at `test_agent_copilot.py:366`
for the measured event(s) only, and add
`test_additional_context_is_still_dropped_on_<event>` *(proposed)* for each
event the probe did not cover.

**Probe still needed.** P2-context (§3.2) — the one with the widest blast
radius in the adapter.

### 2.6 Config document

**Now.** `{"version": 1, "hooks": {<native>: [{"matcher"?, "command"}]}}`
(`copilot.py:173`, `:384`, `:575-581`), two files by ownership
(`copilot.py:165-166`, ADR-047 Evolution 2026-09-19).

**Evidence.** evidence §4: the written shape loads and fires on 1.0.89; nested
and `bash` shapes load too; a missing `version` and an unknown top-level key are
both tolerated. Trust/approval of a fresh hook stays **unmeasured** (evidence
§4 *Trust*).

**Change.** Remove the "cannot verify" language from `copilot.py:168-172` and
ADR-047 §6 — the shape is now `run`. Keep `version: 1`: tolerance of its absence
is one version's leniency, and the key costs nothing. Keep ownership by
filename (ADR-047 §5); the tolerated `description` key makes a stamp possible,
not useful.

**Effect on builtins.** None; this confirms the deployed document is live.

**Tests.** No new behaviour, so no new test; the docstring change is prose.
The existing plan tests stand.

**Probe still needed.** None for the shape. P0-trust (§3.2) for the approval
flow. `disableAllHooks` and enterprise lockdown stay unprobed by choice (§6).

### 2.7 Matcher

**Now.** `_hook_groups` passes `HookEntry.matcher` through verbatim
(`copilot.py:575-578`); deploy fills it from the builtin's Claude-spelled
matcher (`deploy/engine.py:475`, `loader.py:394`). So a Copilot profile today
receives `Bash` (`loader.py:201`), `Read` (`:232`), `Edit|Write` (`:159`,
`:222`) and `Bash|Read|Edit|Write|NotebookEdit` (`:242`), against tool names
`bash`, `view`, `edit`. The `*` matcher of `herdr-context-gauge` (`:140`) does
not reach a Copilot document today: deploy omits the gauge's signal-bearing
placements on an agent without `TOKEN_USAGE` (§2.2).

**Evidence.** None. evidence §4 *`matcher`* is still probe 4; every probe
document omitted the key.

**Consequence for an accepted claim.** ADR-047 Consequences says
`pre-tool-use-security` "is live on the command half". That rests on the
1.0.83 runs (multi-agent design `:2107-2124`, `:2172-2189`), which record no
matcher on the hook they registered. The *deployed* security hook
carries `Bash|Read|Edit|Write|NotebookEdit`; if Copilot's matcher is a
case-sensitive regex or a literal, it matches no Copilot tool and the command
denylist is **not** live on a deployed profile. This is unmeasured either way
and is the first item of Phase 0's probe list.

**Change.** Decided by P4 (§3.2), in one of two shapes (D3):

- **Translate.** `_hook_groups` rewrites each alternative through a table
  `_MATCHER_NAMES` *(proposed)* (`Bash`→`bash`, `Read`→`view`, `Edit`/`Write`→
  `edit`; `NotebookEdit`, `Grep` dropped), in the syntax P4 measured.
- **Omit.** `_hook_groups` never writes `matcher` for Copilot, and every hook
  fires on every call of its event; the builtins already self-filter — on
  `Operation` (`pre_tool_use_security.py:622-659`) and, for most, also on the
  native name (§2.2).

**Effect on builtins.** Decides whether the guards in §2.2/§2.3 fire at all.

**Tests.** For translate: `test_claude_matcher_is_rewritten_to_copilot_names`
*(proposed)*, plus a test that a matcher with no Copilot counterpart drops the
entry with a deploy diagnostic rather than writing a matcher that matches
nothing. For omit: `test_matcher_is_never_written` *(proposed)*, replacing
`test_agent_copilot.py:479-482`. Either way, an integration test drives
`deploy` for a Copilot profile and asserts on the written document.

**Probe still needed.** P4-matcher (§3.2) — **blocking**.

### 2.8 Timeouts

**Now.** No `timeoutSec` written (`copilot.py:575-581`); `HookEntry` has no
timeout field (`base.py:575-585`); no adapter writes one.

**Evidence.** evidence §3 *Timeout*: fails **open** (1.0.83 run); the default is
unmeasured (probe 3, not covered on 1.0.89).

**Change.** Write `timeoutSec` on every Copilot entry from a module constant
`HOOK_TIMEOUT_SEC` *(proposed)*, sized from P3's measured default and a measured
p99 of `lh hook pre-tool-use-security` latency. A per-hook value on `HookEntry`
is not needed until a hook needs a different budget. See D2.

**Effect on builtins.** Every `DENY`-carrying hook (`pre-tool-use-security`,
`pre-tool-use-git-scope`) is enforced only while it answers within the budget.
The value is a security parameter, not a convenience.

**Tests.** `test_every_entry_carries_timeout_sec` *(proposed)*, both documents;
a round-trip test (plan → write → re-plan from the written `existing`) that the
external merge preserves a user's own `timeoutSec` and does not add a second
entry for it.

**Probe still needed.** P3-timeout (§3.2).

### 2.9 MCP placement

**Now.** `servers` ignored, `mcp_config_file()` is `""`
(`copilot.py:321-328`, `:602-608`); deploy and doctor name the gap
(`doctor_cmd.py:702`, ADR-047 Evolution 2026-09-18).

**Evidence.** evidence §5 *`mcp_config_file()`*: probe 7, not run.

**Change.** If P7 shows `$COPILOT_HOME/mcp-config.json` is read, place servers
there **as a merge**, never a rewrite — Copilot writes the file itself
(ADR-047 §7) — with ownership keyed by server id, the way Codex places its
`[mcp_servers]` section inside a `config.toml` it shares with the user
(`codex.py:486`). If P7 shows it is not read, the gap stays and the doctor line
names P7's result instead of "no target".

**Effect on builtins.** None; affects MCP servers only. `preMcpToolCall`'s
payload (evidence §2) becomes measurable in the same run.

**Tests.** Merge round trip: existing user server preserved, harness server
added, second plan is a no-op; invalid existing JSON refuses the plan (the
external-hooks merge already does this, `copilot.py:463-475`).

**Probe still needed.** P7-mcp (§3.2).

### 2.10 System docs — two destinations

**Now.** `[Path("copilot-instructions.md")]` (`copilot.py:632-646`).

**Evidence.** evidence §5 *`system_docs()`*: **both**
`copilot-instructions.md` and `instructions/<name>.instructions.md` load, and
they stack.

**Change.** **Keep one destination.** `system_docs()` promises the agent loads
every entry and `render_agent_md` writes identical bytes to each (`base.py:732-735`);
because the two stack, returning both would put the rendered document into
context twice. The measurement turns the second path from "unknown" into
"known and deliberately unused". Update the docstring at `copilot.py:640-645`
and ADR-047 §9 accordingly. See D6 for the alternative.

**Effect on builtins.** None.

**Tests.** Existing `system_docs` tests stand; add a docstring-independent
assertion that the list has one entry whose name is not a glob.

**Probe still needed.** None for the decision. `**` recursion under
`instructions/` is unmeasured and irrelevant while one destination is kept.

### 2.11 Skills root

**Now.** `skill_root()` returns `None` (`copilot.py:186-188`).

**Evidence.** None. The 1.0.89 package ships a `builtin-skills/` directory
(`src`), which says the feature exists and nothing about a user-level root.

**Change.** None until P8-skills (§3.2) runs a positive-and-negative discovery
probe of the shape ADR-059 used for Codex (`codex.py:928-945`): one skill under
each candidate root in a throwaway home, and a control with none.

**Tests.** On a positive result, `test_skill_root_is_<measured path>`
*(proposed)* plus the disable/negative case if the vendor has one.

**Probe still needed.** P8-skills.

### 2.12 Headless (`-p`)

**Now.** `HeadlessAgent` not implemented (`copilot.py:27-31`).

**Evidence.** evidence §5 *`headless`*: on 1.0.89, `-p` prints the answer and
tool lines on stdout and a usage footer (`AI Credits`, `Tokens ↑ … ↓ …`) on
stderr. `HeadlessAgent.parse_headless_result` receives stdout only
(`base.py:365-384`), so the footer is out of its reach as specified.

**Change.** Implement `resolve_model`, `headless_argv`,
`parse_headless_result` only after P9-headless names a structured output mode,
or decides plain text is the contract. With plain text, `HeadlessResult.output`
is stdout and every metadata field is `None` — allowed by the protocol, which
must not raise (`base.py:378-384`).

**Tests.** Per method, against recorded fixtures from P9; the parse test feeds
malformed output and asserts it degrades, never raises.

**Probe still needed.** P9-headless: output modes, model flag, prompt on stdin
(the protocol sends it there, `base.py:367-370`), exit code on refusal.

### 2.13 `TranscriptReader`, sessions and metrics

**Now.** No reader; `lh doctor` reports Copilot transcripts `unread`
(`doctor_cmd.py:277-279`, `:326`). `session_dirs()` names `session-state`
(`copilot.py:610-618`).

**Evidence.** evidence §5 *`session_dirs()`* (log, 1.0.83) and §6. The 1.0.89
package's `schemas/session-events.schema.json` is 898 KB by a directory listing
recorded in evidence §6, against the 783 KB the multi-agent design records for
the 1.0.83 file. The sizes differ; the contents were **not** diffed, so what
changed is unknown. That is enough to rule out reusing one version's reader for
another unchecked, and not enough to say what moved.

**Change.** Step 12's method unchanged: generate the reader from the schema of
the version being read. Because the schema file differs between versions, the reader keys on the
`copilotVersion` each session file declares (evidence §5) and refuses a version
it was not generated for rather than misreading it. Metrics map
`totalPremiumRequests` / AI credits into `MetricEvent` with the per-seat billing
model already in place (ADR-050, PR #364).

**Tests.** Reader over a recorded `events.jsonl` per supported version; refusal
test for an unknown `copilotVersion`; ingest test that a Copilot session yields
`cost_source="subscription"`.

**Probe still needed.** P10-transcript: one real 1.0.89 `events.jsonl`, keys and
types only, diffed against the 1.0.83 log observation.

### 2.14 Bypass levels

**Now.** `None` for all three (`copilot.py:648-663`); `lh run --bypass` errors.

**Evidence.** None measured. The 1.0.89 `app.js` contains `--allow-all-tools`,
`--allow-all-paths`, `--allow-all-urls`, `--allow-all`, `--yolo` and
`--no-sandbox` (`src`). The probes themselves ran with `--allow-all-tools`, and
`permissionRequest` still fired three times under it (evidence §1), so that flag
does not suppress the permission event.

**Change.** None until P11-bypass measures what each flag grants, per ADR-049's
three levels. Map a level only to a flag whose effect matches it exactly; a
level with no exact flag stays `None` (ADR-049).

**Tests.** Per mapped level, the argv; per unmapped level, the error naming the
agent and level (existing behaviour).

**Probe still needed.** P11-bypass.

### 2.15 Doctor and deploy diagnostics

**Now.** Doctor reports operation gaps (`doctor_cmd.py:641`), uncarried events
(`:677`), MCP gaps (`:702`) and unread transcripts (`:326`). It does not report
hook timeouts (ADR-047 Consequences), Claude-spelled matchers on a non-Claude
agent, or channels an adapter drops.

**Change.**

1. A **dropped-channel** line: a deployed hook whose only output channel
   (`additional_context` / `system_message`) the adapter does not emit on that
   event is reported as silent, the way `_render_hook_operations` reports an
   inert operation. Today this would name `pre-tool-use-read-size` and
   `pre-tool-use-memory-size` on Copilot.
2. A **structure** line: a deployed hook whose declared operation is mapped
   (`_TOOL_OPERATIONS`) but whose argument structure the parser never fills —
   today `view` → `READ_FILE` with `reads = ()`. The existing operation report
   cannot say this (`hooks/event_surface.py:70-83`, `:103`; §2.3). Test: a
   profile installing `pre-tool-use-read-size` on the current adapter must
   produce the line, and after §2.3 must not.
3. A **matcher** line, if D3 picks *translate*: an entry whose matcher had no
   Copilot counterpart and was dropped.
4. A **timeout** line on Copilot: each `DENY`-capable hook with its
   `timeoutSec` and the fail-open note.
5. The **version** line from §2.16.

**Tests.** One per line, each fed a profile that must produce it and one that
must not.

**Probe still needed.** None.

### 2.16 Version drift

**Now.** Docstrings and evidence cite 1.0.83; the run is 1.0.89; the local
package cache already holds 1.0.91. Nothing in the code records which version
the adapter was measured against.

**Change.** A module constant `MEASURED_VERSION = "1.0.89"` *(proposed)* in
`copilot.py`, bumped only by a commit that re-runs the probe and updates the
evidence. `lh doctor` compares it against the installed binary's version and
reports drift as a warning, never a failure — the precedent is the pinned-tool
check (`features.py:87-113`, `memory/engram.py:14`). The probe script prints
the version it ran against (it already does, first line), and each evidence cell
names it. Policy:

- **Patch drift** (e.g. 1.0.89 → 1.0.91): warn; re-run phase 0 and the
  P4-matcher probe before the next release that touches the adapter.
- **Minor/major drift**: warn and recommend the full probe set before trusting
  any guard.

**Tests.** `test_measured_version_is_a_version_string` *(proposed)*; doctor
test with an installed version equal, newer-patch and newer-minor.

**Probe still needed.** None; the policy schedules the re-runs.

## 3. Phase 0 — fix the probe harness, then run the remaining probes

### 3.1 Harness defects, as TDD work items

All three are in `specs/gates/probes/`, outside `src/`, and each gets a failing
test in `tests/unit/test_copilot_probe_summary.py` (or a new sibling) first.

| # | Defect (evidence, *Probe-harness defects*) | Failing test first | Fix |
|---|---|---|---|
| H1 | Summary reads one JSON object per line; Copilot writes payloads with no trailing newline (`copilot_probe_summary.py:71-75`). | `test_concatenated_objects_on_one_line_are_all_counted` *(proposed)*: a sink of three objects with no separators reports three records. | Decode with `json.JSONDecoder.raw_decode` in a loop; keep the "half-written last object is counted, not raised" behaviour (`test_copilot_probe_summary.py:153`). Optionally also make the sink handler append a newline (`copilot-probe1.sh:117`), but the reader must not depend on it. |
| H2 | `command_ran` greps the marker, which appears in the prompt and in denied tool lines (`copilot-probe1.sh:287`). | A summary-function test over a recorded denied stdout (`✗ … Denied by preToolUse hook: probe control`) that must report `ran=no`, and an allowed one (`●`) that must report `ran=yes`. Requires moving the classifier from inline shell into the Python printer so it is testable. | Classify on the tool line (`●` vs `✗`) and the `Denied by` text; make the command's **side effect** the ground truth instead — the command writes a file, and `ran` is that file's existence. |
| H3 | `nonce_reached_model` asks the model to echo hidden context; the model refuses (`copilot-probe1.sh:283-284`). | A test that the phase-2 prompt does not contain "repeat" / "verbatim" (a guard against reintroducing the method), plus a test of the new classifier over recorded outputs. | Use a behavioural nonce: the context says "if asked for the probe colour, answer `<nonce>`"; the prompt asks for the probe colour without mentioning context. Control: the same prompt with no hook — must not produce the nonce. |

The control-row warning (`copilot-probe1.sh:292-293`) stays and becomes a hard
failure: if the control is not classified as blocked, phase 2 exits nonzero.

### 3.2 Probes still needed

Run from a plain terminal, never from an agent pane (evidence, *Probes a
correr*). In priority order:

| ID | Question | Method sketch | Unblocks |
|---|---|---|---|
| **P4-matcher** | Is `matcher` literal, glob or regex; case-sensitive; does `*` work; does `Bash` match `bash`; does omission fire on every call? | One home per matcher value (`bash`, `Bash`, `bash\|view`, `Bash\|Read`, `*`, `.*`, omitted) on `preToolUse`, one prompt driving `bash`+`view`+`edit`; sink per value. | §2.7, and whether ADR-047's "security live on the command half" holds for a deployed profile. **Blocking.** |
| **P3-timeout** | Default timeout when `timeoutSec` is omitted; is `timeoutSec` still honoured on 1.0.89? | Handler sleeping N s for N in a ladder, with and without `timeoutSec`; side-effect file shows whether the tool ran. | §2.8 |
| **P2-context** | Do `additionalContext` / `systemMessage` reach the model on `sessionStart`, `preToolUse` and `postToolUse`? | Behavioural nonce (H3) per channel per event, with a no-hook control per event. The `postToolUse` leg injects after a tool call and asks the follow-up question in the same turn. | §2.5, per event — `sessionStart` for `context-inject`/`session-start-preflight`, `preToolUse` for read-size/memory-size, `postToolUse` for ansible-lint. The widest blast radius. |
| **P2-allow** | Does `allow` override a would-be prompt? | Run **without** `--allow-all-tools`, a tool that would otherwise be refused in `-p`, hook returning `allow`; control without the hook. | §2.4 |
| **P2-ask-interactive** | Does `ask` prompt in an interactive session? | Manual, interactive; record the screen. | §2.4 |
| **P1-events** | Payloads of `postToolUseFailure` (trigger: `view` of a missing path), `preMcpToolCall`, `preCompact`, `notification`, `subagentStart`/`Stop`; `sessionStart.source` on resume. | Phase 1 with corrected triggers; MCP leg shares P7's home. | §2.1 |
| **P1-edit** | Deletion of text (empty, `null` or missing `new_str`?), create, replace-all, two-file change; any other write tool. | Phase 1 prompts per case; the deletion leg asks to remove one line from the fixture, and the summary records `new_str`'s JSON type and whether the key is present. | §2.2 — deletion semantics before any are encoded; completeness |
| **P1-view-range** | Does `view` carry a range key for a partial read? | Prompt for lines 2-3 of a long file. | §2.3 completeness |
| **P7-mcp** | Is `$COPILOT_HOME/mcp-config.json` read? | One stdio server in a throwaway home; ask the model to list its tools; control without the file. | §2.9 |
| **P8-skills** | Which user-level skill root is discovered? | One skill per candidate root, plus a no-skill control. | §2.11 |
| **P9-headless** | Output modes, model flag, prompt on stdin, refusal exit code. | Direct runs, no hooks. | §2.12 |
| **P10-transcript** | 1.0.89 `events.jsonl` keys and types. | One `-p` run, read `session-state/<uuid>/events.jsonl` keys only. | §2.13 |
| **P11-bypass** | What each candidate flag grants. | ADR-049's two-destination method, per flag. | §2.14 |
| **P0-trust** | Does a freshly written hook document fire without an approval step, interactively and in `-p` **without** `--allow-all-tools`? | Clean `COPILOT_HOME`, one hook, an interactive session recorded on screen; then `-p` without the flag. | §2.6; records the approval flow the 1.0.89 run did not observe. |
| P5-interp | `${COPILOT_PROJECT_DIR}` interpolation. | Lowest priority; nothing depends on it. | — |

## 4. Phased delivery

Each phase is one PR, smallest safe unit, gated by `/tdd-check`.

| Phase | Content | Depends on |
|---|---|---|
| **A** | Probe-harness fixes H1-H3 (§3.1). | — |
| **B** | Evidence + ADR record of the 1.0.89 run (this document's companion edit, already in `copilot-evidence.md`) and the ADR text chosen in D1. Prose only. | — |
| **D** | Maintainer runs P4-matcher and P3-timeout with the fixed harness; results into evidence. | A |
| **C** | Adapter: `edit` → `MODIFY_FILE` with string-only `FileEdit`; `view` → `reads`. Builtins *(proposed)*: `"edit"` in `EDIT_TOOLS`, an `edit` projection in `memory-size`, `"view"` in read-size's `INSPECTED_TOOLS`. Consumer tests per §2.2/§2.3; `base.py` docstring corrections. | **D** (P4 result) |
| **E** | Matcher translate-or-omit (§2.7) and `timeoutSec` (§2.8). | C, D, D2, D3 |
| **F** | Payload completions: `toolResult`, `permissionRequest.toolInput` (§2.1). | — |
| **G** | Doctor lines: dropped channel, timeout, matcher, version (§2.15, §2.16). | E for the matcher/timeout lines |
| **H** | Maintainer runs P2-context, P2-allow; then context channels and verdicts (§2.4, §2.5). | A |
| **I** | P7-mcp → MCP merge (§2.9). | A |
| **J** | P8, P9, P10, P11 → skills root, `HeadlessAgent`, `TranscriptReader`, bypass. One PR each. | A |
| **K** | `docs/agents/copilot.md`, backlog and roadmap entries (§7). | each feature PR updates its own row |

C waits on D. Its effect on a deployed profile depends on matcher semantics
nobody has measured: if Copilot ignores the key, matches case-insensitively or
aliases names, `pre-tool-use-security` (matcher `Bash|Read|Edit|Write|NotebookEdit`,
`loader.py:242`) may already fire on `view` and `edit`, and C's filled `reads`
and `edits` would change what it denies (`pre_tool_use_security.py:622-659`).
No claim that C is behaviour-neutral, or that it only touches hooks without a
deny path, is made before P4. With P4 in hand, C ships with a guard regression
test: the security hook, fed Copilot payloads through the Copilot parser, denies
exactly what it denies for the equivalent Claude Code payload. Activation of any
builtin is claimed only from an observed effect on a Copilot run after deploy.

## 5. Open decisions for the maintainer

**D1. Evolution of ADR-047, or a new ADR?** The next free number is **070**
(`specs/adrs/` ends at 069; no branch carries a 07x file).

- *Evolution sections in ADR-047*: keeps one record for one adapter; the ADR
  already uses dated Evolutions (2026-09-16, -18, -19). Cost: ADR-047 §1's rule
  is unchanged, but §3, §4, §6, §9 and most Consequences change verdict, and
  a 300-line ADR read top-down states the opposite of its Evolutions.
- *New ADR-070, superseding ADR-047's decisions 3, 4, 6 and 9*: a clean
  statement of the completed adapter, ADR-047 stays the record of why it shipped
  half. Cost: two documents to read for one adapter.

**Recommendation:** ADR-070, "CopilotAdapter is first-class", with ADR-047
marked *Superseded in part by ADR-070* on the decisions it changes. The change
is not an amendment of one decision; it reverses the posture of four.

**D2. Timeout value.** Options: the measured vendor default (if P3 finds one);
a fixed harness value (e.g. 10 s); a per-hook value on `HookEntry`.
Tradeoff: higher is safer (fail-open needs the hook to be slower than the
budget) and slower (every tool call waits on the hook on its slow path).
**Recommendation:** one module constant set to max(measured default, 3 ×
measured p99 of the slowest deny hook), no per-hook field until a hook needs it.

**D3. Matcher: translate or omit?** *Translate* keeps hooks off irrelevant tool
calls (fewer processes, less timeout exposure) and needs a name table that
drifts with the vendor. *Omit* is vendor-proof and relies on builtins
self-filtering (they do, on `Operation` and mostly on native name — §2.2), at
the cost of a hook process on every tool call. Since C now carries the
native-name changes and waits on P4, the choice also decides whether C's
`EDIT_TOOLS` addition is the only gate (omit) or one of two (translate).
**Recommendation:** translate, if P4 shows a regex or alternation
syntax; omit, if it shows a literal-only matcher.

**D4. `ALLOW`/`ASK`: declare when measured, or never?** No builtin emits them.
Declaring them is contract completeness; not declaring them keeps
`format_hook_output` one channel wide. **Recommendation:** declare a verdict
only when a probe shows it changes an outcome *and* a builtin needs it.

**D5. `sessionStart.source`: map `new` → `startup`?** One observed value, no
consumer. **Recommendation:** do not map until a builtin reads `source`; record
the vocabulary in the evidence only.

**D6. One system-doc destination or two?** Two would let the harness split a
user-level document across files (e.g. one per role) — but `render_agent_md`
writes one document to every destination (`base.py:732-735`), so two today means
the same text twice. **Recommendation:** one, until the system-doc renderer
supports distinct content per destination.

**D7. F8 gate third leg.** ADR-047 deferred it until an edit tool was known;
it is now known. Options: extend in Phase C (which now waits on P4 anyway, so
the matcher semantics are at least measured), or a separate PR after E (when
the adapter's matcher output is settled). **Recommendation:** after E, so the gate's expected
live/inert sets are written once against the final matcher behaviour.

## 6. Risks

- **Deployed guards may not fire at all (P4).** Claude-spelled matchers
  (`loader.py:201`, `:242`) are written verbatim into the Copilot document.
  Until P4 runs, no claim that a Copilot guard is live on a *deployed* profile
  is supported — including the command arm ADR-047 calls live.
- **Fail-open timeout.** A slow guard is a missing guard (evidence §3). Any
  added latency in `lh hook` — startup, imports, a cold cache — erodes the
  margin. P3 and D2 bound it; the doctor timeout line makes it visible.
- **Confounded context probe.** The 1.0.89 run cannot say whether
  `additionalContext` reaches the model (defect 3). Shipping §2.5 on its
  suggestive refusal text would be encoding a guess. H3 fixes the method.
- **`allow` measured under `--allow-all-tools`.** The only `allow` observation
  is undecidable (evidence §3); P2-allow must run without the flag.
- **Enterprise lockdown.** `strictPluginOnlyCustomization` can drop every hook
  the harness writes (evidence §4). A deploy cannot see it; doctor cannot
  either without a firing test. Recorded as the first suspect for "deployed but
  never fires"; no probe is planned because it needs a managed account.
- **Version drift.** Two facts were first observed on 1.0.89 — a document with
  no `version` loads, and `permissionRequest` carries `hookName` — and neither
  can be dated: 1.0.83 has a `version: Required` *string* (evidence §4) but no
  measured rejection, and no recorded `permissionRequest` payload (evidence §1).
  The local package cache already holds 1.0.91 (evidence, header). The adapter's
  evidence ages per patch release. §2.16 makes the age visible; it cannot make
  it current.
- **Vendor-owned files.** An MCP merge into `mcp-config.json` writes a file
  Copilot also writes (ADR-047 §7). A rewrite would destroy user state; the
  merge must preserve unknown keys and refuse invalid JSON.

## 7. Edits proposed outside this document

Not made here; each belongs to the phase named.

- **ADR**: per D1, ADR-070 *(proposed)* or Evolution sections in ADR-047; either
  way ADR-047 §6 loses "cannot verify", Consequences gain the matcher risk
  (§2.7), the native-name gates (§2.2) and the read-size/memory-size channel
  finding (§2.3, §2.5). Phase B.
- **`src/lazy_harness/agents/copilot.py` docstrings** at `:1-31`, `:133-148`,
  `:168-172`, `:565-568`, `:640-645`: rewritten in the PRs that change the
  behaviour they describe (C, E, B).
- **`base.py:151-153`** (multi-file claim) and **`base.py:209`**
  (`result_type`): Phase C and F. Also the comment at
  `hooks/builtins/pre_tool_use_memory_size.py:262`, which repeats the
  multi-file claim about Copilot's `edit`: Phase C.
- **`docs/agents/copilot.md`**: the "partial … 1.0.83" intro (`:3-6`) and the
  *cannot do yet* table (`:79-85`) change per feature PR. Phase K.
- **`specs/backlog.md`**: one entry per phase A–J when opened; the ADR-047
  entry stays as history.
- **`docs/roadmap.md`**: a "Copilot first-class" item listing phases C, E, H
  as the user-visible milestones.
- **Multi-agent design `:1310-1312`** (stale "no hook has fired") — nothing to
  do: the design already carries a dated correction at `:1314-1320`. That
  correction's own citations (`:1201`, `:2071-2098`) predate a line shift and
  now point elsewhere; fixing them is that file's lane.
