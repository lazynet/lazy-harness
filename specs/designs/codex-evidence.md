# Codex dialect evidence — payload schema, command parsing, response format, state keying

**Status:** incomplete — probes not yet run.
**Binary:** `codex-cli 0.154.0` (local: confirmed via `codex --version`, 2026-09-16).
**Scope:** step 9's `CodexAdapter` implements `system_docs()` on its own lane. This
document owns one thing only, per ADR-041's evidence standard — *"a name in a
binary is evidence of a name, and of nothing else"* — for the one gap the F8
gate names in its own header as unresolved: **what Codex's real wire dialect is
for a file edit**, as opposed to the shell command the adapter has actually
observed.

**Why an edit and not another command.** `CodexAdapter._TOOL_OPERATIONS`
(`src/lazy_harness/agents/codex.py:92`) maps exactly one native tool name,
`Bash -> RUN_COMMAND`, and the docstring above it says why: "the shell tool was
exercised, so only the shell tool is mapped — a tool absent here parses with
`operation=None`". Every other contract question below (payload shape, verdict
envelope, trust key) has already been run against the binary and is cited from
`specs/adrs/041-multi-agent-hook-contract.md` and
`specs/designs/2026-09-13-multi-agent-harness-design.md`. Only the edit dialect
has zero runs behind it — `apply_patch` appears in the design doc's provider
table tagged `(source)`, never `(run)` or `(log)`.

Every "observado" cell below is empty on purpose. It gets filled by pasting the
output of the matching probe in **Probes a correr**, run from an Aqua terminal —
Claude Code's own session policy refused `codex exec` on 2026-09-16 before it
ran (recorded in `specs/backlog.md`'s F8 entry and in `translation-gate.sh`'s
own header).

## 1. Payload schema

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Event envelope | Design doc line 431-441: snake_case, `hook_event_name`, `transcript_path`, `tool_name`, `tool_input`, `tool_use_id` — captured **for a `Bash`/`PreToolUse` call**, `(run, 0.154.0)`. | `parse_hook_input` (`codex.py:147-176`) reads exactly those keys via `isinstance` guards; docstring calls the shape "Claude-shaped, and that is an observation, not an assumption" — but the observation backing it is the Bash payload above. | **Probe 1.** Paste the raw JSON `hooks.json` dumped for a `PreToolUse` fired by a file-edit prompt. Confirm every key `parse_hook_input` reads is present with the same casing, and note any key present in the edit payload that is absent from the Bash one (or vice versa). |
| `tool_input` shape for an edit | Not run. Design doc line 1009 only asserts *that* `apply_patch` can touch several files in one call, not the field names it arrives with. | `_parse_tool` (`codex.py:178-191`) reads `arguments.get("command")` — a field that makes sense for `Bash`, not for an edit. For any other tool name it stores `raw_input=arguments` unread. | **Probe 1** (same capture). Record the actual key names Codex puts under `tool_input` for an edit — paths, old/new text, patch hunks, whatever it is — so a real `_parse_tool` branch for edits can be typed against them instead of guessed. |
| `hook_event_name` value for the same call | Design doc's Bash capture shows `"hook_event_name":"PreToolUse"`. | `_HOOK_EVENTS["pre_tool_use"] = HookSupport("PreToolUse", ...)` (`codex.py:81`) — assumes the event name is stable across tool types, which is a reasonable inference but unverified for an edit specifically. | **Probe 1.** Confirm `hook_event_name` is still literally `"PreToolUse"` for an edit call, not e.g. `"PreApplyPatch"` or an event outside `CODEX_EVENT_NAMES` (`codex.py:43-58`) — an unrecognised event name is dropped by Codex with **no diagnostic of any kind** per that constant's own comment. |

## 2. Command / tool-call parsing

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Native tool name for an edit | Design doc line 1196 (provider table): `apply_patch`, tagged **`(source)`** — read off Rust source, never exercised. Contrast `Bash`, tagged `(run)` at the same table and confirmed again at line 1048: `exec_command` normalises to `"Bash"` on the wire. | `_TOOL_OPERATIONS = {"Bash": Operation.RUN_COMMAND}` (`codex.py:92`) has no entry for whatever the edit tool's native name turns out to be, so `operation` comes back `None` for it regardless of what that name is. | **Probe 2.** From the same capture as probe 1, read `tool_input`'s parent object's `tool_name` (or wherever the tool identifier actually lives — Probe 1 settles the field name too). Is it literally `"apply_patch"`? Is it `"Edit"` (Codex renormalising to Claude's name, the way it does for `Bash`)? Is it something else entirely? |
| Downstream field construction (`reads` / `edits`) | `ToolCall.edits: tuple[FileEdit, ...] = ()` and `.reads: tuple[Path, ...] = ()` (`agents/base.py:87,91`) — both default empty, populated per-adapter. | `CodexAdapter._parse_tool` never sets either field — confirmed by reading the method (`codex.py:178-191`): it returns a `ToolCall` with only `native_name`, `operation`, `command`, `raw_input` set. `edits` and `reads` are always `()` under `CodexAdapter`, independent of `tool_name`. | **Probe 2** (same capture). Confirms this needs no live run to establish — it is a static fact about the shipped code, verified above by reading it, not asserted from the docstring. Recorded here so the F8 section below can cite it without re-deriving it. |
| Multi-file edits in one call | Design doc line 1009: "Codex's `apply_patch` … can touch several files in one call". Cited from the same source-only evidence as the tool name. | N/A — nothing reads `tool_input` for edits at all yet. | **Probe 3.** Force a prompt that edits two files in one turn (see script). Does Codex emit one `PreToolUse`/`PostToolUse` pair per file, or one call carrying both? This changes whether `ToolCall.edits` needs to be a tuple built from one payload or accumulated across several hook invocations. |

## 3. Response format (verdict envelope)

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Refusal envelope, `PreToolUse` | Design doc line 408-421 and `codex.py:193-227`'s own docstring: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`, stdout, exit 0 — **observed for a `Bash` refusal**: the file the model was told to create was never created, `codex exec` echoed the reason back verbatim. | `format_hook_output` builds the identical envelope regardless of which tool triggered the hook — there is nothing tool-specific in the function, so the envelope itself is not in question. | **Probe 4.** Fire the same `deny` verdict for a `PreToolUse` on the edit tool (whatever `Probe 2` finds its native name to be) via a hook that always denies. Confirm Codex refuses the edit the same way it refused the shell command — same log line shape, same "file never created"-style effect, and specifically that the *file the edit targeted is unchanged on disk*. |
| `allow` / `ask` on an edit | ADR-041 §"a hook whose verdict the agent will not honour": `allow` without `updatedInput` and `ask` are both rejected as `"unsupported permissionDecision"` and Codex **fails open** — observed for `PreToolUse`/`Bash` (`codex.py:66-71`). `_HOOK_EVENTS["pre_tool_use"].verdicts == frozenset({Verdict.DENY})` (`codex.py:81`) already encodes only `deny` as honoured, for any tool. | Same code path handles every tool identically — `format_hook_output` raises `ValueError` before emitting anything Codex hasn't been shown to honour, so there is no tool-specific branch to falsify here either. | **Probe 4** (optional second run). If time allows, confirm `ask`/`allow` on an edit also fails open (tool runs, warning logged) rather than behaving differently for `apply_patch` than for `exec_command` — no reason to expect a difference, but the evidence standard is "a claim about behaviour is confirmed by running the path," not by generalising from one tool. |

## 4. State keying (hook trust)

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Trust key shape | Design doc line 763-779: `<absolute path of declaring file>:<snake_case event>:<group index>:<handler index>` — path-scoped, **measured** on 0.154.0 with a `PreToolUse`/`Bash` hook (the byte-identical-handler probe that found `hooks.json` trusted while the identical `config.toml` declaration read `new · review required`). | `codex.py:104-109` states the choice ("hooks.json") is "frozen at the first deploy" on the strength of that same measurement — the key is derived from *event name and position in the file*, not from the tool the hook happens to guard. | **Probe 5 (lower priority — likely a non-finding).** The trust key formula names no tool at all, so an edit-triggering hook trusted the same way should behave identically. Worth one confirmation run only if Probe 1-4 raise something unexpected about how Codex treats a `PreToolUse` group whose matcher targets the edit tool specifically (e.g. a `matcher` naming `apply_patch` rather than firing unconditionally) — `_hook_groups` (`codex.py:269-295`) says an *empty* matcher was the only form observed to fire on every call; a matcher naming a specific edit tool has never been tried. |
| Matcher on a named tool | `_hook_groups`'s own docstring (`codex.py:276-281`): "An empty string was never observed, and the observed form that fires on every tool call is the one with no key at all." | The harness currently emits no per-tool matchers for Codex at all — every builtin gets an unconditional group. | **Probe 5.** If a matcher naming the edit tool's native name (from Probe 2) is tried, confirm whether Codex's matcher syntax accepts a bare tool name the way an empty matcher fires on everything, or whether it needs a different syntax (regex, glob) — this only matters once a Codex-specific hook wants to scope itself to edits alone, which nothing in the harness does yet. |

## Probes a correr

Run these from an Aqua terminal, in order. Each is self-contained and creates
its own disposable `CODEX_HOME`. **Do not run `codex exec` from inside a Claude
Code session** — that's the policy that blocked the 2026-09-16 attempt, and
re-hitting it from here just burns another attempt for no new evidence.

Auth lives at `~/.codex/auth.json`; a disposable `CODEX_HOME` needs it copied in
or `codex login` run again inside it. All four probes copy it.

### Probe 1 + 2 — payload schema and tool-name for a single-file edit

```bash
#!/usr/bin/env bash
set -euo pipefail

WORK="$(mktemp -d)"
export CODEX_HOME="$(mktemp -d)"
cp ~/.codex/auth.json "$CODEX_HOME/auth.json"

# Trust the hook up front so the run measures the payload, not the trust prompt.
# The harness's own choice of file (codex.py:110) is hooks.json; probes use the
# same file so what's observed matches what lh deploy would actually write.
cat > "$CODEX_HOME/hooks.json" <<'JSON'
{
  "description": "codex-evidence probe — dumps every PreToolUse/PostToolUse payload",
  "hooks": {
    "PreToolUse": [
      { "hooks": [ { "type": "command", "command": "/bin/sh -c 'cat >> '\"$CODEX_HOME\"'/pre_tool_use.jsonl; echo'" } ] }
    ],
    "PostToolUse": [
      { "hooks": [ { "type": "command", "command": "/bin/sh -c 'cat >> '\"$CODEX_HOME\"'/post_tool_use.jsonl; echo'" } ] }
    ]
  }
}
JSON
# CODEX_HOME isn't expanded inside the JSON heredoc above the way the outer
# shell expands it — rewrite the two commands with the real path substituted so
# the sink is unambiguous regardless of how Codex invokes the handler's shell.
python3 - "$CODEX_HOME" <<'PY'
import json, sys
home = sys.argv[1]
p = f"{home}/hooks.json"
doc = json.load(open(p))
doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = f"/bin/sh -c 'cat >> {home}/pre_tool_use.jsonl; echo'"
doc["hooks"]["PostToolUse"][0]["hooks"][0]["command"] = f"/bin/sh -c 'cat >> {home}/post_tool_use.jsonl; echo'"
json.dump(doc, open(p, "w"), indent=2)
PY

mkdir -p "$WORK"
cd "$WORK"
git init -q
printf 'first line\nsecond line\n' > target.txt
git add -A && git commit -q -m 'seed'

# --dangerously-bypass-hook-trust: this is a throwaway CODEX_HOME with nothing
# else in it, so there's no live trust state to protect and no interactive TUI
# to click through. Never pass this against a real ~/.codex.
codex exec \
  --dangerously-bypass-hook-trust \
  --sandbox workspace-write \
  --skip-git-repo-check \
  -C "$WORK" \
  --json \
  "Edit target.txt: change 'first line' to 'FIRST LINE'. Make exactly one edit, then stop." \
  > "$CODEX_HOME/exec-transcript.jsonl" 2>&1

echo "payloads: $CODEX_HOME/pre_tool_use.jsonl and post_tool_use.jsonl"
echo "target.txt after run:"; cat "$WORK/target.txt"
```

**Output files → evidence cells:**
- `$CODEX_HOME/pre_tool_use.jsonl` → §1 "Event envelope" and "`tool_input` shape
  for an edit" rows, and §2 "Native tool name for an edit" row.
- `$CODEX_HOME/post_tool_use.jsonl` → same rows, confirms the payload is stable
  across the two events.
- `$WORK/target.txt`'s final content → sanity check that the edit actually ran
  (if the hook sink works but the file is unchanged, something above is wrong
  in a way worth noting before trusting the rest).

### Probe 3 — multi-file edit in one turn

Same setup as Probe 1, second working tree, different prompt:

```bash
#!/usr/bin/env bash
set -euo pipefail
WORK="$(mktemp -d)"
export CODEX_HOME="$(mktemp -d)"
cp ~/.codex/auth.json "$CODEX_HOME/auth.json"
# ... same hooks.json as Probe 1 (copy it in, or point CODEX_HOME/hooks.json
# at a copy) ...

cd "$WORK"
git init -q
printf 'alpha\n' > a.txt
printf 'beta\n' > b.txt
git add -A && git commit -q -m 'seed'

codex exec \
  --dangerously-bypass-hook-trust \
  --sandbox workspace-write \
  --skip-git-repo-check \
  -C "$WORK" \
  --json \
  "Edit both a.txt (append 'ALPHA') and b.txt (append 'BETA') in the same turn." \
  > "$CODEX_HOME/exec-transcript.jsonl" 2>&1

echo "payloads: $CODEX_HOME/pre_tool_use.jsonl"
wc -l "$CODEX_HOME/pre_tool_use.jsonl"
```

**Output → evidence cell:** §2 "Multi-file edits in one call" — count the
`PreToolUse` records: one per file means one `ToolCall` per file (matches the
`Bash` shape), more than one field per record means a single call already
carries both paths.

### Probe 4 — deny an edit

Same setup, `hooks.json` swapped for one whose `PreToolUse` handler always
denies:

```bash
#!/usr/bin/env bash
set -euo pipefail
WORK="$(mktemp -d)"
export CODEX_HOME="$(mktemp -d)"
cp ~/.codex/auth.json "$CODEX_HOME/auth.json"

cat > "$CODEX_HOME/hooks.json" <<'JSON'
{
  "description": "codex-evidence probe — always-deny PreToolUse",
  "hooks": {
    "PreToolUse": [
      { "hooks": [ { "type": "command", "command": "/bin/sh -c 'echo {\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"codex-evidence probe: deny-all\"}}'" } ] }
    ]
  }
}
JSON

cd "$WORK"
git init -q
printf 'untouched\n' > target.txt
git add -A && git commit -q -m 'seed'

codex exec \
  --dangerously-bypass-hook-trust \
  --sandbox workspace-write \
  --skip-git-repo-check \
  -C "$WORK" \
  --json \
  "Edit target.txt: change 'untouched' to 'touched'." \
  > "$CODEX_HOME/exec-transcript.jsonl" 2>&1

echo "target.txt after a denied edit (must be unchanged if the deny worked):"
cat "$WORK/target.txt"
grep -i 'block\|den' "$CODEX_HOME/exec-transcript.jsonl" || echo "(no block/deny text found in transcript — paste the full transcript instead)"
```

**Output → evidence cell:** §3 "Refusal envelope, `PreToolUse`" — paste
`target.txt`'s final content (should read `untouched`) and the matching
transcript lines into that row.

## Lo que el gate F8 ya midió y el evidence tiene que confirmar o falsificar

`specs/gates/f8/translation-gate.sh` runs entirely between two Python objects —
the shipped `ClaudeCodeAdapter` and the shipped `CodexAdapter` — and says so in
its own header (lines 88-106): *"the `codex` binary is never invoked, and the
payloads are written in Claude Code's dialect."* Concretely, its
`payload_for_operation` (line 352) feeds the *literal* Claude Code payload
`{"tool_name":"Edit","tool_input":{"file_path":"/f8/probe.py",...}}` to **both**
translators, including the one under `CodexAdapter`. That payload assumes the
exact fact this document's §2 says is unverified: that Codex's wire `tool_name`
for an edit is `"Edit"`. If Probe 2 instead finds `"apply_patch"` (the
source-only name the design doc carries), the gate's own inputs never exercised
the real case at all — it measured "what happens if Codex sent Claude's tool
name," not "what Codex actually sends."

**Measured 2026-09-16, by reading the code, confirmed above in §2:**
`CodexAdapter._parse_tool` (`codex.py:178-191`) never populates `ToolCall.edits`
or `.reads` for *any* tool name — those fields default to `()` and nothing in
the method sets them. This is why the ADR's account needed correcting: the
`operation` gate is the *first* of two, not the only one.

Per builtin, the two guards it actually hits under `CodexAdapter` today:

| Builtin | First guard | Result under Codex | Second guard | Result under Codex |
|---|---|---|---|---|
| `post-tool-use-format` | `tool.operation is not Operation.MODIFY_FILE` (`post_tool_use_format.py:32`) | Fails here: `operation` is `None` for any `tool_name` other than `"Bash"`, since `_TOOL_OPERATIONS` (`codex.py:92`) maps nothing else — regardless of what Probe 2 finds the real name to be, until that mapping is extended. | `for edit in tool.edits` (`post_tool_use_format.py:36`) | Never reached — the hook returns at the first guard. |
| `pre-tool-use-read-size` | `tool.operation is not Operation.READ_FILE` (`pre_tool_use_read_size.py:105`) | Same as above — no native name maps to `READ_FILE` today. | `for path in tool.reads` (`pre_tool_use_read_size.py:119`) | Never reached. |
| `pre-tool-use-memory-size` | `tool.native_name not in INSPECTED_TOOLS` where `INSPECTED_TOOLS = {"Edit", "Write"}` (`pre_tool_use_memory_size.py:44,225`) | **Depends on Probe 2.** `native_name` is the raw `tool_name` from the payload, untranslated — if Codex's wire name is literally `"Edit"`, this guard *passes*. If it's `"apply_patch"`, it fails here, before the second guard is ever reached. | `for edit in tool.edits` (`pre_tool_use_memory_size.py:234`) | If the first guard passes, this is reached — and `tool.edits` is always `()` under `CodexAdapter`, so the loop body never executes regardless of what Probe 2 finds. |
| `post-tool-use-sync-claude` | Same `INSPECTED_TOOLS` check (`post_tool_use_sync_claude.py:32,76`) | Same dependency on Probe 2 as above. | `tuple(edit.path for edit in tool.edits)` (`post_tool_use_sync_claude.py:78`) | Always empty under `CodexAdapter`, same as above. |
| `post-tool-use-ansible-lint` | Same `INSPECTED_TOOLS` check (`post_tool_use_ansible_lint.py:33,113`) | Same dependency on Probe 2. | `for edit in tool.edits` (`post_tool_use_ansible_lint.py:122`) | Always empty under `CodexAdapter`, same as above. |

**What this means for "ensanchar `_TOOL_OPERATIONS` es un no-op."** That claim
is fully established for two of the five builtins (`post-tool-use-format`,
`pre-tool-use-read-size`) independent of anything the probes find — their first
guard reads `operation`, which stays `None` for any unmapped name, and their
second guard is unreachable regardless. It is **conditionally** established for
the other three: their first guard reads `native_name`, a raw string the
adapter never translates, so whether they're "inert because of the second gate"
or "inert because the first gate never even passes" depends on whether Probe 2
finds Codex's real edit tool name to be `"Edit"` or something else. Either way
the second gate (`tool.edits` always `()`) makes the mapping fix a no-op for
all five — but the *reason* three of them are inert changes depending on the
probe result, and the F8 gate's own payload (`tool_name: "Edit"`, hard-coded)
could not have told the difference, because it never tried Codex's real name.

**If the probes contradict the F8 gate's inert/live split** — e.g. Probe 2
finds Codex genuinely does normalise the edit tool's name to `"Edit"` and a
correctly-populated `edits` tuple would flip some of these five to live — the
finding is exactly what F8's own header names as the boundary of what it can
prove: it measured two Python objects agreeing with each other, which is sound
for "does the shipped adapter pair regress" and says nothing about whether the
shipped `CodexAdapter` matches the binary. That would not make F8 wrong about
what it tested; it would confirm the gap its header already discloses.

## Pendiente

Todas las celdas "Observado" de las tablas de arriba, y la fila de la tabla de
F8 marcada "Depends on Probe 2" (tres builtins), quedan sin cerrar hasta que el
usuario corra los cuatro probes desde una terminal Aqua y pegue la salida acá.
