# Copilot dialect evidence — hook payload, tool vocabulary, response envelope, config shape

**Status:** `specs/gates/probes/copilot-probe1.sh` was run once, against
**`copilot 1.0.89`, on 2026-10-02**, from a plain terminal. Cells it answers say
so with **run, 1.0.89, 2026-10-02**; the artifacts were re-read directly (keys, types and
the tool lines of each run's stdout), because the script's own summary is wrong
in three places — see [Probe-harness defects](#probe-harness-defects-found-by-the-1089-run).
Values beyond key and type are cited only where that re-read printed them:
`toolName`, `hookName`, `source`, `reason` and `resultType` values, list lengths
of `permissionSuggestions`, whether `path` values were absolute and under `cwd`,
and the full stdout of all six phase-2 runs. The re-read was done on
2026-10-02 against the run's temporary artifact directory, which is not
retained. Cells the run did not answer keep their probe number. Observations against
`copilot 1.0.83` that the multi-agent design records as `run` or `log` are kept
as they were; where 1.0.89 differs, the cell says so.

**Binary:** `copilot 1.0.83` for the cited rows; `copilot 1.0.89` for the
2026-10-02 run (`GitHub Copilot CLI 1.0.89.` on the probe's first line). The
local package cache already also holds `1.0.91`, so the version measured is not
the version a user runs for long — see the version-drift policy in
`2026-10-02-copilot-completion-design.md`. Launcher at `/opt/homebrew/bin/copilot`. The
launcher is a Node SEA shim and carries no hook vocabulary; the vendor artifact
this document reads is the extracted package tree at
`~/Library/Caches/copilot/pkg/darwin-arm64/1.0.83/` (`app.js`, `copilot-sdk/`,
`schemas/session-events.schema.json`, `prebuilds/darwin-arm64/runtime.node`).

**Scope.** `CopilotAdapter` (`src/lazy_harness/agents/copilot.py`, ADR-047)
ships only the half the design marks `run` or `log`. This document is the list
of everything else: one row per contract the adapter needs, what the design or
the vendor artifact claims, what the adapter assumes today, and — empty for now
— what a probe measured.

**Evidence marks** are the design's own (`specs/designs/2026-09-13-multi-agent-harness-design.md:1180-1190`):
`run` (the binary was driven and its behaviour read), `log` (observed in a
session log on this machine), `binary` / `src` (a string or a type in the
installed artifact — proves the name exists and nothing about whether it is
live), `docs` (vendor documentation), `none`.

**The gate this document exists to satisfy**, from `CLAUDE.md`: *for an adapter
over an external binary the probes come first — run them for the undocumented
contract (payload schema, command parsing, response format, state keying),
record observed-vs-spec here, and correct the design before the first test.*
Step 11 inverts the order out of necessity: the adapter ships the `run`-backed
subset now and the probe closes the rest, which is the trade ADR-047 records.

## A correction to the design, found while writing this

`specs/designs/2026-09-13-multi-agent-harness-design.md:1285` reads **"Still
unobserved: `~/.copilot/hooks/` exists and remains empty … No hook has fired on
either agent."** That paragraph is stale and is contradicted three times inside
the same file: `:1201` marks `$COPILOT_HOME/hooks/*.json` **run, 1.0.83 —
registered and fired**; `:2071-2098` quotes the literal `preToolUse` payload a
hook registered there received; `:2135-2160` runs a four-envelope deny matrix
through one. It is the failure the document names two paragraphs above itself —
a provenance label ageing while the prose around it moved on. The design is not
edited here (it is another lane's file); the correction is recorded in ADR-047
and in this lane's PR body.

## 1. Hook payload schema

| | Design / vendor artifact says | `CopilotAdapter` assumes | Observado |
|---|---|---|---|
| `preToolUse` envelope | `:2107-2119` and `:445-450`, **run, 1.0.83**: `{"sessionId": str, "timestamp": int (epoch ms), "cwd": str, "toolName": str, "toolArgs": object}`. Explicitly **not** the PascalCase compat shape. | `parse_hook_input` reads exactly `sessionId`, `cwd`, `toolName`, `toolArgs`, each behind an `isinstance` guard, and puts the whole payload in `raw`. | **Cited from the design's run** (1.0.83). **run, 1.0.89, 2026-10-02**: unchanged — five phase-1 records and one per phase-0 shape, every one exactly `{sessionId: str, timestamp: int, cwd: str, toolName: str, toolArgs: object}`. |
| `cwd` vs `workingDirectory` | The wire says `cwd` (`:2113-2114`, run). The shipped SDK's `BaseHookInput` says `workingDirectory` (`copilot-sdk/types.d.ts:1034-1041`, src). The two disagree. | Reads `cwd` only. A fallback to `workingDirectory` would encode a `src` row as behaviour. | **run, 1.0.89, 2026-10-02**: `cwd: str` on every event that fired — `preToolUse`, `postToolUse`, `permissionRequest`, `sessionStart`, `sessionEnd`; `workingDirectory` on none. The wire wins over the SDK. **Still probe 1** for the six events that did not fire (`postToolUseFailure`, `preMcpToolCall`, `preCompact`, `notification`, `subagentStart`, `subagentStop`). |
| Event name on the wire | Absent. The payload carries no `hook_event_name`/`hookEventName` field (`:450-455`, run) — the adapter is told which event it was invoked for. | `parse_hook_input(event=...)` supplies the canonical name from its argument and never reads the payload for it. | **Cited from the design's run** (1.0.83). **run, 1.0.89, 2026-10-02**: still absent on `preToolUse`, `postToolUse`, `sessionStart`, `sessionEnd`. **Newly observed on one event:** `permissionRequest` carries `hookName` (value `permissionRequest` on all three records). No 1.0.83 `permissionRequest` payload was ever recorded (row below), so whether this is new in 1.0.89 is unknown. The adapter's caller-supplied name stays correct; nothing needs to read it. |
| `transcript_path` | Absent on the `preToolUse` wire (`:453-455`, run). The SDK declares `transcriptPath` on `AgentStopHookInput` only (`types.d.ts:1272-1285`, src) — and `agentStop` is **not** one of the eleven the declarative loader accepts. | `HookEvent.transcript_path` is always `None`. | **run, 1.0.89, 2026-10-02**: absent under any spelling on all five events that fired. **Still probe 1** for the six that did not. |
| `tool_use_id` | Absent from the observed payload. The SDK declares `toolCallId` on `PreMcpToolCallHookInput` (`types.d.ts:1068-1075`, src) and on nothing else. | Always `None`. | **run, 1.0.89, 2026-10-02**: no `toolCallId`, `tool_use_id` or similar key on `preToolUse`, `postToolUse` or `permissionRequest`, so a pre/post pair cannot be joined by id. `preMcpToolCall` did not fire — the SDK's `toolCallId` there is **still probe 1** (MCP leg, folded into probe 7). |
| `tool_response` | The SDK declares `PostToolUseHookInput.toolResult: ToolResultObject` (`types.d.ts:1096-1101`, src). Never observed on the declarative wire. | Always `None`. `post_tool_use` builtins reading a tool response see nothing. | **run, 1.0.89, 2026-10-02**: **delivered.** All five `postToolUse` records carry `toolResult: {resultType: str, textResultForLlm: str}` beside the same `toolName`/`toolArgs` as the matching `preToolUse`. `resultType` was `success` on all five. Note the camelCase `resultType`: `agents/base.py:209` describes it as `{result_type, ...}`. |
| `postToolUseFailure` shape | The SDK says the host CLI does **not** forward the full result to a failure hook — only `error`, a string (`types.d.ts:1117-1131`, src). | Not read. The event is declared in `hook_events()`; nothing maps `error` into `HookEvent`. | **run, 1.0.89, 2026-10-02**: **did not fire.** The prompt's failing step was the shell command `false`; it produced an ordinary `postToolUse` with `resultType: success`. A nonzero shell exit is a successful *tool call*. **Still probe 1**, with a corrected trigger: a tool-level failure (a `view` of a path that does not exist). |
| `sessionStart.source` | The SDK declares `source: "startup" \| "resume" \| "new"` (`types.d.ts:1202-1207`, src). The canonical `HookEvent.source` is Claude's `startup\|resume\|clear\|compact` — a **different** vocabulary, not a subset. | Always `None`. Nothing translates the two vocabularies. | **run, 1.0.89, 2026-10-02**: `sessionStart` is `{sessionId: str, timestamp: int, cwd: str, source: str, initialPrompt: str}`, `source` = `new` on a fresh `-p` run. `initialPrompt` is not in the SDK row. `startup` and `resume` were not exercised — **still probe 1** (resume leg). |
| `permissionRequest` payload | Named in the accepted eleven (`:1224`, run) and nowhere else. No SDK type, no observed payload. | Declared in `hook_events()`, parsed by the same generic reader; no event-specific field. | **run, 1.0.89, 2026-10-02**: three records (`bash`, `bash`, `edit`) **although the run passed `--allow-all-tools`**: `{hookName: str, sessionId: str, timestamp: int, cwd: str, toolName: str, toolInput: object, permissionSuggestions: list}` (`permissionSuggestions` of length 0 in all three, per the re-read). **`toolInput`, not `toolArgs`** — and its inner keys differ from the same tool's `preToolUse` arguments: `bash` → `{command}` (no `description`), `edit` → `{file_path, diff}` (not `{path, old_str, new_str}`). The generic reader looks for `toolArgs`, so a `permission_request` `ToolCall` today has empty `raw_input` and `command=None`. Whether any verdict is honoured on this event is unmeasured. |
| PascalCase compat mode | `docs` only, never observed firing. `_vsCodeCompat` is the only candidate switch, it is a **string** on the matcher group, and an arbitrary value (`"zzz"`) changed neither payload nor verdict (`:2084-2099`, run). | Not used, not emitted, not read. | **Closed against the binary already** — the design's own run (1.0.83). Not re-run on 1.0.89. Nothing here depends on it. |
| `sessionEnd` payload | No row in the 1.0.83 evidence. | Parsed by the generic reader; `reason` is not mapped. | **run, 1.0.89, 2026-10-02**: `{sessionId: str, timestamp: int, cwd: str, reason: str}`, `reason` = `complete` on a `-p` run that finished normally. Other `reason` values unobserved. |

## 2. Tool vocabulary and `tool_input` shape

| | Design / vendor artifact says | `CopilotAdapter` assumes | Observado |
|---|---|---|---|
| Native tool names | `bash`, `view`, `rg`, `glob`, `task`, `skill`, `web_fetch` — lowercase, from a real session (`:1231`, **log, 1.0.83**); `web_search` appears in the same session count at `:1290`. Copilot does **not** normalise to Claude Code's names (`:1289-1293`, log). | `_TOOL_OPERATIONS` maps two: `bash -> RUN_COMMAND`, `view -> READ_FILE`. Every other name parses with `operation=None`. | **Cited from the design's log** (1.0.83). **run, 1.0.89, 2026-10-02**: the hook wire carried `bash`, `view` and **`edit`** — the third is not in `COPILOT_TOOL_NAMES`. Still lowercase, still unnormalised. |
| `bash` arguments | `toolArgs = {"command": str, "description": str}` — a nested JSON object, **not** a JSON-encoded string, which is the one documented detail the run contradicted (`:2113-2119`, run). | `_parse_tool` reads `toolArgs["command"]` into `ToolCall.command` behind an `isinstance` guard. | **Cited from the design's run** (1.0.83). **run, 1.0.89, 2026-10-02**: unchanged — `{command: str, description: str}` on every `bash` record, pre and post. |
| `view` arguments | **Nothing.** No run, no log, no SDK type names the key that carries the path. | `view` maps to `READ_FILE` and `reads` stays `()`. The operation gate opens and the structure gate does not — which is the F8 gate's own finding restated (`specs/gates/f8/translation-gate.sh:56-78`): a mapping without a structure revives nothing. | **run, 1.0.89, 2026-10-02**: `toolArgs = {path: str}` on both `view` calls, pre and post. The path was absolute, under `cwd`. No offset/limit key appeared — but the read was of a whole two-line file, so absence on this call says nothing about a ranged read. **Still probe 1** (ranged-read leg). |
| The edit tool | **Unknown, and it is the largest gap.** No run and no log has ever recorded Copilot editing a file. `apply_patch` and `str_replace_editor` appear as strings in `prebuilds/darwin-arm64/runtime.node`, in the subagent-orchestrator string region (src) — which per the design's first gate establishes that the names exist and nothing else. | No `MODIFY_FILE` mapping at all. `edits` and `deletes` are always `()`. | **run, 1.0.89, 2026-10-02**: **the edit tool is `edit`**, `toolArgs = {path: str, old_str: str, new_str: str}`, `path` absolute, and the fixture changed from `untouched` to `touched`. Neither `apply_patch` nor `str_replace_editor` appeared on the wire. File creation, deletion and replace-all were not exercised — **still probe 1** for those legs. |
| Multi-file edits | `agents/base.py:80-86` names "Copilot's `edit`" as a tool that can touch several files in one call. That sentence predates every Copilot measurement and no source is recorded for it. (It now sits at `agents/base.py:151-153`.) | Nothing. | **run, 1.0.89, 2026-10-02**: the one observed `edit` call carried one `path` and one `old_str`/`new_str` pair — a single file. That does not prove the tool is single-file, and nothing supports the multi-file claim. **Still probe 1** for the negative (a prompt that asks for two files in one change). |
| `preMcpToolCall` arguments | The SDK declares `{toolCallId?, serverName, toolName, arguments, _meta?}` (`types.d.ts:1068-1075`, src). Note `arguments`, not `toolArgs`. | Parsed by the generic reader, which looks for `toolArgs` — so an MCP call yields `command=None`. | **Probe 1**, MCP leg (needs an MCP server configured in the throwaway home). Not fired on 1.0.89: the run configured no MCP server. Folded into probe 7. |

## 3. Response format (verdict envelope)

| | Design / vendor artifact says | `CopilotAdapter` assumes | Observado |
|---|---|---|---|
| `deny` on `preToolUse` | **Top-level and unwrapped**, on stdout, exit 0: `{"permissionDecision":"deny","permissionDecisionReason":"<reason>"}` produced `✗ … Denied by preToolUse hook: <reason>` and the command did not run (`:2172-2189`, run, four envelopes varied against a control). Corroborated by `PreToolUseHookOutput` in `copilot-sdk/types.d.ts:1052-1058` (src). | `format_hook_output` emits exactly those two keys, top level, stdout, exit 0; `hook_events()["pre_tool_use"].verdicts == {DENY}`. | **Cited from the design's run** (1.0.83). **run, 1.0.89, 2026-10-02** (phase 2 control): `✗ … Denied by preToolUse hook: probe control`. Unchanged. |
| `hookSpecificOutput` wrapper | Read, logged as `[hook stdout]` text, and **ignored** — the command ran (`:2144`, run). | Never emitted. A test asserts the literal does not appear in the adapter's output. | **Cited from the design's run.** |
| `allow` / `ask` | Declared in the SDK's output union (`types.d.ts:1053`, src). **Never observed being honoured.** | `format_hook_output` raises `ValueError` for either. Declaring them would let deploy install a guard whose approvals nothing checks. | **run, 1.0.89, 2026-10-02**: `allow` → the tool ran (`●`). `ask` → `✗ … Denied by preToolUse hook (unable to ask user for confirmation): probe` — **in `-p` mode `ask` degrades to deny**. Two limits: the run passed `--allow-all-tools`, so the tool would have run anyway and `allow` *being honoured* is not distinguishable from `allow` *being ignored*; and interactive `ask` was not exercised. **Still probe 2** for both. |
| Exit 2 | A second refusal route: produced `Denied by preToolUse hook: hook exited with code 2` (`:423-425`, run). | Not used. One refusal channel is emitted, the one whose reason text Copilot echoes back. | **Cited from the design's run**; the adapter's choice between the two is ADR-047's. |
| Nonzero exit, no output | Fails **closed** — `Denied by preToolUse hook from "<file>" (hook errored)` (`:2104-2106`, run). | Nothing depends on it; `cli/hooks_cmd.py` ends every path in `sys.exit(0)`. | **Cited from the design's run.** |
| Timeout | Fails **OPEN**: a hook with `timeoutSec: 2` that slept 6s was abandoned and the command executed (`:2142-2143`, run). | `plan_config` emits no `timeoutSec` at all, so the vendor default applies — and that default is unmeasured. | **Probe 3.** What is the default, and does omitting the key mean "no timeout" or "some default"? On Copilot this is a security parameter, not a convenience. Not covered by the 1.0.89 run. |
| `additionalContext` | Named in the 1.0.40 bundle (`:38`, binary) and declared on four SDK output types (src). One occurrence in `runtime.node`, and Rust deduplicates string literals, so its position says nothing about which code path uses it. **Never observed being read on the declarative wire.** | **Not emitted.** A `HookDecision.additional_context` is dropped. | **Probe 2.** This is the single row with the widest blast radius: every context-injecting builtin reaches Copilot through this key or not at all. **run, 1.0.89, 2026-10-02**: **inconclusive.** The key was accepted (the tool ran, `●`) and the nonce was not echoed, but the probe's echo method is confounded (defect 3): in each of the six phase-2 runs (stdouts re-read) the model declined to repeat its context, the control included. Only in this run did the refusal name "that hook message", which is suggestive and not proof. Measured on `preToolUse` only; `sessionStart`, where `context-inject` runs, was not tested. **Still probe 2**, with a non-echo design. |
| `systemMessage`, `continue`, `stopReason`, `suppressOutput` | `systemMessage` in the 1.0.40 bundle (`:38`, binary); `suppressOutput` in `PreToolUseHookOutput` (src) and in the declarative string region. `{"continue":false,"stopReason":"…"}` was run and **ignored** (`:2182`, run). | None emitted. | `continue`/`stopReason` **closed by the design's run**. The other two are **Probe 2**. **run, 1.0.89, 2026-10-02**: both keys accepted without error and the tool ran (`●`). `systemMessage` reaching the model: inconclusive, as `additionalContext`. `suppressOutput`: no visible difference from the `allow` run (the tool line still printed `└ 1 line…`). **Still probe 2.** |

## 4. Config document shape (`$COPILOT_HOME/hooks/*.json`)

The directory is `run`-backed — a hook registered there was loaded and fired
(`:1201`, `:2072`). **The document's own schema is not.** What follows is read
out of the string region belonging to `src/runtime/src/hooks/declarative.rs` in
`prebuilds/darwin-arm64/runtime.node` (src, 1.0.83), plus one error message the
design quotes from a real load.

| | Vendor artifact says | `CopilotAdapter` assumes | Observado |
|---|---|---|---|
| Top level | `version: Required`, `version: Invalid literal value, expected 1`, `hooks: Required`, `hooks: hooks must be an object`, `Expected hook config to be an object`, `disableAllHooks must be a boolean` (src). | Writes `{"version": 1, "hooks": {...}}`. `disableAllHooks` is never written. | **run, 1.0.89, 2026-10-02**: `{"version": 1, "hooks": …}` loads and fires. **A document with no `version` key also loaded and fired** — on 1.0.89 `version: Required` is not enforced on this path. `version` values other than 1 and `disableAllHooks` were not tested. |
| Event key nesting | `hooks.preToolUse[0]._vsCodeCompat: Expected string — hook will be skipped` (`:2121-2124`, run) — so `hooks.<event>` is an **array** and its entries are objects. | `hooks[nativeName] = [entry, ...]`, one entry per `HookEntry`, in declaration order. | **Cited from the design's run** for the nesting. **run, 1.0.89, 2026-10-02**: every phase-0 shape fired with `hooks.preToolUse` an array of one object. |
| Handler spelling | `Specify either 'exec' (native executable) or 'bash'/'powershell'/'command' (shell), but not both` (src). Also in the same region: `timeoutSec`, `allowedEnvVars`, `matcher`, `_vsCodeCompat`, and `Nested hooks deeper than one level are not supported.` | Writes `"command": "<the command>"` on the entry itself. The nested Claude-shaped `{"hooks":[{"type":"command",...}]}` form is **not** written. | **run, 1.0.89, 2026-10-02**: flat `command` (what the adapter writes), the nested Claude-shaped `{"hooks":[{"type":"command","command":…}]}` and `bash` **all loaded and fired**. The adapter's shape is verified. `exec` and `powershell` were not tested. |
| `matcher` | `matcher cannot be empty` (src). Copilot's tool names are lowercase and unnormalised, so a Claude regex (`Bash\|Edit\|Write`) matches nothing here. | `matcher` is **omitted** when a `HookEntry` carries none, and passed through verbatim when it does. The harness generates none for Copilot today. | **Probe 4.** Is the matcher a literal, a glob or a regex, and is omitting it the form that fires on every call (as it is on Codex)? Not covered by the 1.0.89 run — every probe document omitted `matcher`. **Correction to the middle cell:** the harness *does* generate matchers for Copilot: builtins carry Claude-shaped ones (`hooks/loader.py:159`, `:201`, `:222`, `:232`, `:242` — `Edit\|Write`, `Bash`, `Read`, `Bash\|Read\|Edit\|Write\|NotebookEdit`) and `deploy/engine.py:475` passes them through verbatim. |
| Ownership / deletion | Nothing. The top level looks schema-strict, so a `description` stamp of the kind `CodexAdapter` uses may be rejected outright. | Ownership is the **filename**: the harness writes `hooks/lazy-harness.json` and nothing else, so the user's own hooks live in sibling files under the same glob and deletion keys on the path rather than on a stamp. | **run, 1.0.89, 2026-10-02**: a document with an extra top-level `description` key **loaded and fired**. An unknown top-level key is tolerated on 1.0.89. Ownership by filename stays the decision (ADR-047 §5); it is now a choice, not a constraint. |
| Trust | No trust model observed and none named. Codex's `[hooks.state].trusted_hash` has no Copilot counterpart in any artifact read here. | Nothing. `lh doctor` reports no Copilot hook trust, because there is nothing to report. | **Probe 0.** Does a freshly written hook file fire without an approval step? **Still unmeasured.** The 1.0.89 run did not cover trust or approval and says so; its documents fired from disposable homes (`copilot-probe1.sh:71-76`) under `--allow-all-tools` (`:155`), but no approval flow was observed or looked for, and a firing sink under a bypass flag says nothing about one. Probe P0-trust in the completion design. |
| `${COPILOT_PROJECT_DIR}` / `${CLAUDE_PROJECT_DIR}` | Both appear in the declarative string region (src) — command interpolation the harness does not use. | Nothing. Commands are written fully resolved. | **Probe 5**, lowest priority. |
| Enterprise lockdown | `Skipping repo/workspace hooks: blocked by enterprise customization lockdown (strictPluginOnlyCustomization locks "hooks")` and `disabledHooks` (src). A managed policy can drop hooks the harness wrote. | Nothing. A deploy cannot tell that its hooks were dropped by policy. | **None.** Recorded so a future "deployed but never fires" report has a first suspect. |

## 5. Environment, paths and credentials

| | Design says | `CopilotAdapter` assumes | Observado |
|---|---|---|---|
| `env_var()` | `COPILOT_HOME`, honoured end to end (`:1195`, **run, 1.0.83**). | `env_var() == "COPILOT_HOME"`. | **Cited from the design's run.** |
| `credentials_file()` | `:1195` again, and it is the strongest negative on this page: *every deny-matrix run used a throwaway `COPILOT_HOME`, and auth survived it*. So the credential is **not** under `COPILOT_HOME`. | `None`, and the docstring cites that run rather than the absence of a filename. | **Cited from the design's run.** Stronger than `CodexAdapter`'s `None`, which rests on a file nobody opened (ADR-045 A4). |
| `global_config_link()` | `~/.copilot` holds `permissions-config.json` — `locations.<abs path>.tool_approvals[]`, written by the agent as the user approves things (`:1277`) — plus `settings.json`, `mcp-config.json`, `session-store.db`. | `None`. `deploy/symlinks.py:16-21` renames an existing target to `<name>.bak` before linking, and none of the above is reconstructible. | **Cited from the design's disk observation.** |
| `session_dirs()` | `session-state/<uuid>/events.jsonl`, `{type, data, id, parentId, timestamp}` envelope, self-identifying `"producer":"copilot-agent","copilotVersion":"1.0.83"` (`:1204`, `:1257-1266`, **log, 1.0.83**). | `{"sessions": "session-state", "logs": "", "queue": ""}`. | **Cited from the design's log.** `~/.copilot/logs/` exists on disk but nothing was observed writing it, so it stays unnamed. |
| `system_docs()` | `copilot-instructions.md` and `instructions/**/*.instructions.md` under `$COPILOT_HOME` (`:1222`, **vendor docs**, deliberately left weak by the 2026-09-14 sweep — never exercised). `.github/copilot-instructions.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` are **repository-discovered**, not deploy targets (`:1223`, `:96`). | `[Path("copilot-instructions.md")]` — **one** destination. The glob is not a path and `system_docs()` promises the agent loads every entry it returns; two entries would assert Copilot loads both, which nothing has measured. | **Probe 6.** Write a distinctive marker into each candidate destination in a throwaway home and ask the model to recite it. **run, 1.0.89, 2026-10-02** (phase 3): **both loaded** — `$COPILOT_HOME/copilot-instructions.md` and `$COPILOT_HOME/instructions/probe.instructions.md` each had its marker recited. They stack. Only one directory level under `instructions/` was tried, so the `**` recursion is unmeasured. Because they stack, returning both from `system_docs()` would load the same rendered bytes twice; that is a decision, not a measurement (completion design). |
| `mcp_config_file()` | `mcp-config.json`, `mcpServers.<id>.{type, command, args, tools}` — **present on disk**, and the 2026-09-14 sweep deliberately left it there: *a path that exists is not a path the binary was seen to read* (`:1228`, `:1300`, `:1244-1255`). | `""`, and `plan_config` ignores `servers` entirely. Writing a file the binary was never seen to read, over a document the agent mutates itself, is the failure mode the design's own config table warns about. | **Probe 7.** Write one server into a throwaway home's `mcp-config.json` and ask the model to list its tools. Not covered by the 1.0.89 run. |
| `resolve_binary()` | `/opt/homebrew/bin/copilot` is a Node SEA launcher (`:1209-1216`). | `shutil.which("copilot")`. | **Cited from the design.** |
| `headless` | `copilot -p "…" --allow-all-tools` drove every run (`:1232`, **run, 1.0.83**). | `HeadlessAgent` is **not** implemented. `-p` is known to start a run; nothing has parsed its output. | **None.** Same posture as `CodexAdapter`'s unclaimed `HeadlessAgent`: it waits on a run, not on a decision. **run, 1.0.89, 2026-10-02**, incidental: every `-p` run wrote the assistant's text and its tool lines (`●`/`✗`) to stdout and a usage footer to stderr (`Changes +N -N`, `AI Credits <n> (<s>)`, `Tokens ↑ … ↓ …`). Nothing parsed it; a structured output mode is unmeasured. |

## 6. Transcript

Not this step. `TranscriptReader` for Copilot is step 12, and the design pins
the method: the reader is **generated** from
`~/Library/Caches/copilot/pkg/<platform>/<version>/schemas/session-events.schema.json`
(783 KB, declaring `HookStartData`, `HookEndData`, `HookEndError`,
`PermissionRequestHook` and the rest), not reverse-engineered from samples
(`:1899-1906`). Because the schema is versioned alongside the binary, the *a
transcript schema is only valid for the version it was read from* gate is
satisfied by re-extracting on upgrade.

**1.0.89, 2026-10-02 (directory listing, not a run):** the 1.0.89 package
tree's `schemas/session-events.schema.json` is 898 KB (`ls -la`), beside a
2.0 MB `api.schema.json`. The 783 KB above is the design's figure for the
1.0.83 file. The contents were not diffed. The same listing showed
`1.0.83`, `1.0.85`, `1.0.88`, `1.0.89` and `1.0.91` under
`~/Library/Caches/copilot/pkg/darwin-arm64/`.

One consequence lands in step 11 anyway and is recorded in ADR-047: with
`transcript_path` absent from every observed payload and no reader, every
transcript-dependent builtin is unavailable on Copilot — and `hook_events()`
cannot say so, because that is decision 11's `signals()`, not an absent event
key.

## Probe-harness defects found by the 1.0.89 run

Three defects are in `specs/gates/probes/copilot-probe1.sh` and its summary
printer, not in Copilot. The cells above were filled from the artifacts, re-read
directly, wherever the script's own summary disagreed with them.

1. **The phase 1 summary under-counts to zero.** Each sink handler is
   `cat >> <sink>/<event>.jsonl` (`copilot-probe1.sh:117`), and Copilot 1.0.89
   writes the payload to the hook's stdin with no trailing newline, so a sink
   holding several payloads is one line of concatenated JSON objects. The
   printer reads one object per line (`copilot_probe_summary.py:71-75`), so the
   summary reported `preToolUse`, `postToolUse` and `permissionRequest` as
   `not fired (0 records)`. They fired 5, 5 and 3 times; decoding the sinks with
   `json.JSONDecoder.raw_decode` recovers every object.
2. **Phase 2 `command_ran` is always `yes`.** It greps the marker in stdout
   (`copilot-probe1.sh:287`), but the marker is in the prompt, Copilot prints the
   attempted command line (`│ echo <marker>`) even when the call is denied, and
   the model restates it. The control row reads `command_ran=yes` while its
   stdout says `✗ … Denied by preToolUse hook: probe control`. Outcome has to be
   read from the `●`/`✗` tool line and the `Denied by` text.
3. **Phase 2 `nonce_reached_model` is confounded.** The prompt asks the model to
   repeat any extra context verbatim (`copilot-probe1.sh:283-284`); in all six
   phase-2 runs, the control included, the model declined to repeat its
   system/context text (each run's stdout re-read). A `no` therefore does not show the channel is unread —
   only that the model would not echo it.

The control row's own warning (`copilot-probe1.sh:292-293`) fired as designed:
`control-deny` did not show `command_ran=no`, so the phase-2 summary's negatives
say nothing, and the table in §3 was read from the tool lines instead.

## Probes a correr

**Run these from an Aqua terminal. Never from a Claude Code or Herdr pane** —
that is the standing rule for agent binaries in this repo, and the Codex probes
were blocked by it on 2026-09-16 before they ran.

The whole set is one script, `specs/gates/probes/copilot-probe1.sh`, staged in
phases so an early failure is readable: phase 0 discriminates the hook-document
shape (nothing later means anything until a document loads), phase 1 dumps one
payload per event, phase 2 varies the response envelope, and the summary printer
reports **keys and value types only, never bodies**.

```bash
bash specs/gates/probes/copilot-probe1.sh
```

Each phase builds its own disposable `COPILOT_HOME` under `$(mktemp -d)` and
prints the summary at the end. Paste the summary back into the `Observado`
column above, then reopen ADR-047's Consequences against what it says.

**Status after the 1.0.89 run.** Phases 0 and 3 answered their rows. Phase 1
answered five of eleven events and the `bash`/`view`/`edit` shapes. Phase 2
answered `deny`, `allow`-ran and `ask`-in-`-p`, and left every context channel
inconclusive. Probes 3, 4, 5 and 7 have never run. The remaining set, and the
fixes the script needs before its next run, are listed in
`2026-10-02-copilot-completion-design.md` §3.
