# Copilot dialect evidence — hook payload, tool vocabulary, response envelope, config shape

**Status:** **no probe has been run for this document.** Every `Observado` cell
is empty except where the multi-agent design already records a `run` or a `log`
against `copilot 1.0.83`, in which case the cell cites that line and says so.
The probe script that fills the rest is `specs/gates/probes/copilot-probe1.sh`;
it has never been executed, and it must be run from an Aqua terminal, never from
an agent session.

**Binary:** `copilot 1.0.83`, launcher at `/opt/homebrew/bin/copilot`. The
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
| `preToolUse` envelope | `:2071-2083` and `:445-449`, **run, 1.0.83**: `{"sessionId": str, "timestamp": int (epoch ms), "cwd": str, "toolName": str, "toolArgs": object}`. Explicitly **not** the PascalCase compat shape. | `parse_hook_input` reads exactly `sessionId`, `cwd`, `toolName`, `toolArgs`, each behind an `isinstance` guard, and puts the whole payload in `raw`. | **Cited from the design's run; not re-measured here.** |
| `cwd` vs `workingDirectory` | The wire says `cwd` (`:2078`, run). The shipped SDK's `BaseHookInput` says `workingDirectory` (`copilot-sdk/types.d.ts:1034-1041`, src). The two disagree. | Reads `cwd` only. A fallback to `workingDirectory` would encode a `src` row as behaviour. | **Probe 1.** Which key does each of the eleven events carry? If some event carries only `workingDirectory`, `HookEvent.cwd` is `Path("")` there today. |
| Event name on the wire | Absent. The payload carries no `hook_event_name`/`hookEventName` field (`:450-455`, run) — the adapter is told which event it was invoked for. | `parse_hook_input(event=...)` supplies the canonical name from its argument and never reads the payload for it. | **Cited from the design's run.** |
| `transcript_path` | Absent on the `preToolUse` wire (`:453-455`, run). The SDK declares `transcriptPath` on `AgentStopHookInput` only (`types.d.ts:1272-1285`, src) — and `agentStop` is **not** one of the eleven the declarative loader accepts. | `HookEvent.transcript_path` is always `None`. | **Probe 1.** Does any of the eleven carry a transcript path under any spelling? |
| `tool_use_id` | Absent from the observed payload. The SDK declares `toolCallId` on `PreMcpToolCallHookInput` (`types.d.ts:1068-1075`, src) and on nothing else. | Always `None`. | **Probe 1.** |
| `tool_response` | The SDK declares `PostToolUseHookInput.toolResult: ToolResultObject` (`types.d.ts:1096-1101`, src). Never observed on the declarative wire. | Always `None`. `post_tool_use` builtins reading a tool response see nothing. | **Probe 1**, `postToolUse` leg. |
| `postToolUseFailure` shape | The SDK says the host CLI does **not** forward the full result to a failure hook — only `error`, a string (`types.d.ts:1117-1131`, src). | Not read. The event is declared in `hook_events()`; nothing maps `error` into `HookEvent`. | **Probe 1**, failure leg (needs a command that fails). |
| `sessionStart.source` | The SDK declares `source: "startup" \| "resume" \| "new"` (`types.d.ts:1202-1207`, src). The canonical `HookEvent.source` is Claude's `startup\|resume\|clear\|compact` — a **different** vocabulary, not a subset. | Always `None`. Nothing translates the two vocabularies. | **Probe 1**, `sessionStart` leg. |
| `permissionRequest` payload | Named in the accepted eleven (`:1199`, run) and nowhere else. No SDK type, no observed payload. | Declared in `hook_events()`, parsed by the same generic reader; no event-specific field. | **Probe 1.** |
| PascalCase compat mode | `docs` only, never observed firing. `_vsCodeCompat` is the only candidate switch, it is a **string** on the matcher group, and an arbitrary value (`"zzz"`) changed neither payload nor verdict (`:2084-2099`, run). | Not used, not emitted, not read. | **Closed against the binary already** — the design's own run. Nothing here depends on it. |

## 2. Tool vocabulary and `tool_input` shape

| | Design / vendor artifact says | `CopilotAdapter` assumes | Observado |
|---|---|---|---|
| Native tool names | `bash`, `view`, `rg`, `glob`, `task`, `skill`, `web_fetch` — lowercase, from a real session (`:1206`, **log, 1.0.83**); `web_search` appears in the same session count at `:1265`. Copilot does **not** normalise to Claude Code's names (`:1054-1060`, run). | `_TOOL_OPERATIONS` maps two: `bash -> RUN_COMMAND`, `view -> READ_FILE`. Every other name parses with `operation=None`. | **Cited from the design's log.** |
| `bash` arguments | `toolArgs = {"command": str, "description": str}` — a nested JSON object, **not** a JSON-encoded string, which is the one documented detail the run contradicted (`:2076-2083`, run). | `_parse_tool` reads `toolArgs["command"]` into `ToolCall.command` behind an `isinstance` guard. | **Cited from the design's run.** |
| `view` arguments | **Nothing.** No run, no log, no SDK type names the key that carries the path. | `view` maps to `READ_FILE` and `reads` stays `()`. The operation gate opens and the structure gate does not — which is the F8 gate's own finding restated (`specs/gates/f8/translation-gate.sh:56-78`): a mapping without a structure revives nothing. | **Probe 1**, forced by a prompt that reads a file. Needed keys: the path, and whether an offset/limit pair exists. |
| The edit tool | **Unknown, and it is the largest gap.** No run and no log has ever recorded Copilot editing a file. `apply_patch` and `str_replace_editor` appear as strings in `prebuilds/darwin-arm64/runtime.node`, in the subagent-orchestrator string region (src) — which per the design's first gate establishes that the names exist and nothing else. | No `MODIFY_FILE` mapping at all. `edits` and `deletes` are always `()`. | **Probe 1**, forced by a prompt that edits a file. Until it runs, every edit-gating builtin is inert on Copilot — see ADR-047's Consequences. |
| Multi-file edits | `agents/base.py:80-86` names "Copilot's `edit`" as a tool that can touch several files in one call. That sentence predates every Copilot measurement and no source is recorded for it. | Nothing. | **Probe 1**, once the edit tool has a name. |
| `preMcpToolCall` arguments | The SDK declares `{toolCallId?, serverName, toolName, arguments, _meta?}` (`types.d.ts:1068-1075`, src). Note `arguments`, not `toolArgs`. | Parsed by the generic reader, which looks for `toolArgs` — so an MCP call yields `command=None`. | **Probe 1**, MCP leg (needs an MCP server configured in the throwaway home). |

## 3. Response format (verdict envelope)

| | Design / vendor artifact says | `CopilotAdapter` assumes | Observado |
|---|---|---|---|
| `deny` on `preToolUse` | **Top-level and unwrapped**, on stdout, exit 0: `{"permissionDecision":"deny","permissionDecisionReason":"<reason>"}` produced `✗ … Denied by preToolUse hook: <reason>` and the command did not run (`:2135-2146`, run, four envelopes varied against a control). Corroborated by `PreToolUseHookOutput` in `copilot-sdk/types.d.ts:1052-1058` (src). | `format_hook_output` emits exactly those two keys, top level, stdout, exit 0; `hook_events()["pre_tool_use"].verdicts == {DENY}`. | **Cited from the design's run.** |
| `hookSpecificOutput` wrapper | Read, logged as `[hook stdout]` text, and **ignored** — the command ran (`:2144`, run). | Never emitted. A test asserts the literal does not appear in the adapter's output. | **Cited from the design's run.** |
| `allow` / `ask` | Declared in the SDK's output union (`types.d.ts:1053`, src). **Never observed being honoured.** | `format_hook_output` raises `ValueError` for either. Declaring them would let deploy install a guard whose approvals nothing checks. | **Probe 2.** Same four-envelope method as the deny matrix, varying only the verdict. |
| Exit 2 | A second refusal route: produced `Denied by preToolUse hook: hook exited with code 2` (`:423-425`, run). | Not used. One refusal channel is emitted, the one whose reason text Copilot echoes back. | **Cited from the design's run**; the adapter's choice between the two is ADR-047's. |
| Nonzero exit, no output | Fails **closed** — `Denied by preToolUse hook from "<file>" (hook errored)` (`:2104-2106`, run). | Nothing depends on it; `cli/hooks_cmd.py` ends every path in `sys.exit(0)`. | **Cited from the design's run.** |
| Timeout | Fails **OPEN**: a hook with `timeoutSec: 2` that slept 6s was abandoned and the command executed (`:2106-2108`, run). | `plan_config` emits no `timeoutSec` at all, so the vendor default applies — and that default is unmeasured. | **Probe 3.** What is the default, and does omitting the key mean "no timeout" or "some default"? On Copilot this is a security parameter, not a convenience. |
| `additionalContext` | Named in the 1.0.40 bundle (`:37`, binary) and declared on four SDK output types (src). One occurrence in `runtime.node`, and Rust deduplicates string literals, so its position says nothing about which code path uses it. **Never observed being read on the declarative wire.** | **Not emitted.** A `HookDecision.additional_context` is dropped. | **Probe 2.** This is the single row with the widest blast radius: every context-injecting builtin reaches Copilot through this key or not at all. |
| `systemMessage`, `continue`, `stopReason`, `suppressOutput` | `systemMessage` in the 1.0.40 bundle (`:37`, binary); `suppressOutput` in `PreToolUseHookOutput` (src) and in the declarative string region. `{"continue":false,"stopReason":"…"}` was run and **ignored** (`:2146`, run). | None emitted. | `continue`/`stopReason` **closed by the design's run**. The other two are **Probe 2**. |

## 4. Config document shape (`$COPILOT_HOME/hooks/*.json`)

The directory is `run`-backed — a hook registered there was loaded and fired
(`:1201`, `:2072`). **The document's own schema is not.** What follows is read
out of the string region belonging to `src/runtime/src/hooks/declarative.rs` in
`prebuilds/darwin-arm64/runtime.node` (src, 1.0.83), plus one error message the
design quotes from a real load.

| | Vendor artifact says | `CopilotAdapter` assumes | Observado |
|---|---|---|---|
| Top level | `version: Required`, `version: Invalid literal value, expected 1`, `hooks: Required`, `hooks: hooks must be an object`, `Expected hook config to be an object`, `disableAllHooks must be a boolean` (src). | Writes `{"version": 1, "hooks": {...}}`. `disableAllHooks` is never written. | **Probe 0**, which is the load-discrimination phase of probe 1: every later phase is meaningless if the document does not load. |
| Event key nesting | `hooks.preToolUse[0]._vsCodeCompat: Expected string — hook will be skipped` (`:2087`, run) — so `hooks.<event>` is an **array** and its entries are objects. | `hooks[nativeName] = [entry, ...]`, one entry per `HookEntry`, in declaration order. | **Cited from the design's run** for the nesting; the entry's own keys are probe 0. |
| Handler spelling | `Specify either 'exec' (native executable) or 'bash'/'powershell'/'command' (shell), but not both` (src). Also in the same region: `timeoutSec`, `allowedEnvVars`, `matcher`, `_vsCodeCompat`, and `Nested hooks deeper than one level are not supported.` | Writes `"command": "<the command>"` on the entry itself. The nested Claude-shaped `{"hooks":[{"type":"command",...}]}` form is **not** written. | **Probe 0** enumerates the candidate spellings — flat `command`, nested `hooks[]`, and `exec` — and reads back which load. This is the single shape the adapter cannot verify and does write. |
| `matcher` | `matcher cannot be empty` (src). Copilot's tool names are lowercase and unnormalised, so a Claude regex (`Bash\|Edit\|Write`) matches nothing here. | `matcher` is **omitted** when a `HookEntry` carries none, and passed through verbatim when it does. The harness generates none for Copilot today. | **Probe 4.** Is the matcher a literal, a glob or a regex, and is omitting it the form that fires on every call (as it is on Codex)? |
| Ownership / deletion | Nothing. The top level looks schema-strict, so a `description` stamp of the kind `CodexAdapter` uses may be rejected outright. | Ownership is the **filename**: the harness writes `hooks/lazy-harness.json` and nothing else, so the user's own hooks live in sibling files under the same glob and deletion keys on the path rather than on a stamp. | **Probe 0** also answers whether an unknown top-level key is tolerated — which is what a stamp would need. |
| Trust | No trust model observed and none named. Codex's `[hooks.state].trusted_hash` has no Copilot counterpart in any artifact read here. | Nothing. `lh doctor` reports no Copilot hook trust, because there is nothing to report. | **Probe 0.** Does a freshly written hook file fire without an approval step? (The design's runs suggest yes, but none of them was a *first* write into a clean home with the prompt observed.) |
| `${COPILOT_PROJECT_DIR}` / `${CLAUDE_PROJECT_DIR}` | Both appear in the declarative string region (src) — command interpolation the harness does not use. | Nothing. Commands are written fully resolved. | **Probe 5**, lowest priority. |
| Enterprise lockdown | `Skipping repo/workspace hooks: blocked by enterprise customization lockdown (strictPluginOnlyCustomization locks "hooks")` and `disabledHooks` (src). A managed policy can drop hooks the harness wrote. | Nothing. A deploy cannot tell that its hooks were dropped by policy. | **None.** Recorded so a future "deployed but never fires" report has a first suspect. |

## 5. Environment, paths and credentials

| | Design says | `CopilotAdapter` assumes | Observado |
|---|---|---|---|
| `env_var()` | `COPILOT_HOME`, honoured end to end (`:1195`, **run, 1.0.83**). | `env_var() == "COPILOT_HOME"`. | **Cited from the design's run.** |
| `credentials_file()` | `:1195` again, and it is the strongest negative on this page: *every deny-matrix run used a throwaway `COPILOT_HOME`, and auth survived it*. So the credential is **not** under `COPILOT_HOME`. | `None`, and the docstring cites that run rather than the absence of a filename. | **Cited from the design's run.** Stronger than `CodexAdapter`'s `None`, which rests on a file nobody opened (ADR-045 A4). |
| `global_config_link()` | `~/.copilot` holds `permissions-config.json` — `locations.<abs path>.tool_approvals[]`, written by the agent as the user approves things (`:1277`) — plus `settings.json`, `mcp-config.json`, `session-store.db`. | `None`. `deploy/symlinks.py:16-21` renames an existing target to `<name>.bak` before linking, and none of the above is reconstructible. | **Cited from the design's disk observation.** |
| `session_dirs()` | `session-state/<uuid>/events.jsonl`, `{type, data, id, parentId, timestamp}` envelope, self-identifying `"producer":"copilot-agent","copilotVersion":"1.0.83"` (`:1204`, `:1257-1266`, **log, 1.0.83**). | `{"sessions": "session-state", "logs": "", "queue": ""}`. | **Cited from the design's log.** `~/.copilot/logs/` exists on disk but nothing was observed writing it, so it stays unnamed. |
| `system_docs()` | `copilot-instructions.md` and `instructions/**/*.instructions.md` under `$COPILOT_HOME` (`:1197`, **vendor docs**, deliberately left weak by the 2026-09-14 sweep — never exercised). `.github/copilot-instructions.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` are **repository-discovered**, not deploy targets (`:1198`, `:96`). | `[Path("copilot-instructions.md")]` — **one** destination. The glob is not a path and `system_docs()` promises the agent loads every entry it returns; two entries would assert Copilot loads both, which nothing has measured. | **Probe 6.** Write a distinctive marker into each candidate destination in a throwaway home and ask the model to recite it. This is the row step 11 exists for — the first agent whose destination is not a repo-shaped filename. |
| `mcp_config_file()` | `mcp-config.json`, `mcpServers.<id>.{type, command, args, tools}` — **present on disk**, and the 2026-09-14 sweep deliberately left it there: *a path that exists is not a path the binary was seen to read* (`:1203`, `:1225-1230`). | `""`, and `plan_config` ignores `servers` entirely. Writing a file the binary was never seen to read, over a document the agent mutates itself, is the failure mode the design's own config table warns about. | **Probe 7.** Write one server into a throwaway home's `mcp-config.json` and ask the model to list its tools. |
| `resolve_binary()` | `/opt/homebrew/bin/copilot` is a Node SEA launcher (`:1209-1216`). | `shutil.which("copilot")`. | **Cited from the design.** |
| `headless` | `copilot -p "…" --allow-all-tools` drove every run (`:1207`, **run, 1.0.83**). | `HeadlessAgent` is **not** implemented. `-p` is known to start a run; nothing has parsed its output. | **None.** Same posture as `CodexAdapter`'s unclaimed `HeadlessAgent`: it waits on a run, not on a decision. |

## 6. Transcript

Not this step. `TranscriptReader` for Copilot is step 12, and the design pins
the method: the reader is **generated** from
`~/Library/Caches/copilot/pkg/<platform>/<version>/schemas/session-events.schema.json`
(783 KB, declaring `HookStartData`, `HookEndData`, `HookEndError`,
`PermissionRequestHook` and the rest), not reverse-engineered from samples
(`:1899-1906`). Because the schema is versioned alongside the binary, the *a
transcript schema is only valid for the version it was read from* gate is
satisfied by re-extracting on upgrade.

One consequence lands in step 11 anyway and is recorded in ADR-047: with
`transcript_path` absent from every observed payload and no reader, every
transcript-dependent builtin is unavailable on Copilot — and `hook_events()`
cannot say so, because that is decision 11's `signals()`, not an absent event
key.

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
