# Codex dialect evidence — payload schema, command parsing, response format, state keying

**Status:** probes run 2026-09-16 against `codex-cli 0.154.0` (model
`gpt-6-astra`), from an Aqua terminal, in two rounds. §1, §2, §3 and the F8
reconciliation below are closed against the real binary. The first round's
deny probe used a malformed envelope and produced a misleading reading (a
native edit path that looked unhooked); the second round, probes 4b and 4c,
used a validated envelope and corrected it — see §3 and the F8 section for what
changed and why. §4 (state keying) was not exercised by either round and stays
as originally scoped.
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
envelope, trust key) had already been run against the binary before this
document existed, and is cited from `specs/adrs/041-multi-agent-hook-contract.md`
and `specs/designs/2026-09-13-multi-agent-harness-design.md`. Only the edit
dialect had zero runs behind it going in — `apply_patch` appeared in the design
doc's provider table tagged `(source)`, never `(run)` or `(log)`. Six probes
across two rounds below closed §1, §2 and §3.

Claude Code's own session policy refused `codex exec` on 2026-09-16 before it
ran (recorded in `specs/backlog.md`'s F8 entry and in `translation-gate.sh`'s
own header), so the probes below were run by hand from an Aqua terminal on the
same date, against the real binary, and the raw output pasted back in. The
first round (probes 1-4) closed §1 and §2 but produced one misleading reading
in §3: probe 4's deny hook built its verdict with a hand-escaped `echo`
one-liner, and a malformed envelope reads to Codex as an unsupported
`permissionDecision`, which ADR-041 already documents as **failing open** —
so the edit going through said nothing about whether the hook fired, only that
its (invalid) verdict didn't block. The second round (probes 4b and 4c) used a
validated, `json.dumps`-built envelope and corrected the reading. Recorded
below is the corrected conclusion, not the first round's — with the first
round's mistake named, since it changed what the F8 section below concludes.

## 1. Payload schema

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Event envelope | Design doc line 431-441: snake_case, `hook_event_name`, `transcript_path`, `tool_name`, `tool_input`, `tool_use_id` — captured **for a `Bash`/`PreToolUse` call**, `(run, 0.154.0)`. | `parse_hook_input` (`codex.py:147-176`) reads exactly those keys via `isinstance` guards; docstring calls the shape "Claude-shaped, and that is an observation, not an assumption" — but the observation backing it is the Bash payload above. | **Confirmed identical, run 2026-09-16.** Probe 1's `PreToolUse` record for a file-edit prompt: `session_id`, `turn_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`, `permission_mode`, `tool_name`, `tool_input`, `tool_use_id` — the same key set, same casing, as the design doc's Bash capture quoted above. No key was added or dropped for an edit prompt. `PostToolUse` adds one key, `tool_response` (observed as `""` in this run). Every key `parse_hook_input` reads was present. (The probe run's own notes flagged these as "extra keys beyond the design doc's capture" — checked against the doc's quoted payload at line 435-441 and that's not accurate: the design doc's Bash capture already carries every one of these keys. Recorded here as confirmation, not discrepancy.) |
| `tool_input` shape for an edit | Not run. Design doc line 1009 only asserts *that* `apply_patch` can touch several files in one call, not the field names it arrives with. | `_parse_tool` (`codex.py:178-191`) reads `arguments.get("command")` — a field that makes sense for `Bash`, not for an edit. For any other tool name it stores `raw_input=arguments` unread. | **Resolved for both edit paths.** For the `Bash`-mediated edit, `tool_input` is `{"command": "<python heredoc>"}` — ordinary `Bash` shape. For the native `apply_patch` path (probe 4c, forced by prompt and confirmed with a validated deny that blocked it), `tool_input` is **also** `{"command": "<raw patch text>"}` — the *same key*, `command`, but the value is a full patch blob: `*** Begin Patch\n*** Update File: <abs path>\n@@\n-old\n+new\n*** End Patch`. There is no structured path/old-text/new-text field; the touched path is embedded as a `*** Update File: <path>` line inside the blob text. `_parse_tool`'s existing `arguments.get("command")` read technically captures this string for `apply_patch` too — it just has no idea it's a patch rather than a shell command, and does nothing to extract the path from it. |
| `hook_event_name` value for the same call | Design doc's Bash capture shows `"hook_event_name":"PreToolUse"`. | `_HOOK_EVENTS["pre_tool_use"] = HookSupport("PreToolUse", ...)` (`codex.py:81`) — assumes the event name is stable across tool types, which is a reasonable inference but unverified for an edit specifically. | **Confirmed for both edit paths.** `"PreToolUse"` fired with `tool_name: "Bash"` for the heredoc edits, and — once probe 4c used a validated deny so the block was actually observed — `"PreToolUse"` also fired with `tool_name: "apply_patch"` for the native path, and the block took effect (`target.txt` stayed `"untouched"`, transcript logged `Command blocked by PreToolUse hook`). The first round's reading that the native path produced no `hook_event_name` at all was an artefact of that round's malformed deny envelope (Codex fails open on an invalid `permissionDecision`, so the edit proceeding said nothing about whether the hook fired) — **withdrawn**, corrected here. |

## 2. Command / tool-call parsing

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Native tool name for an edit | Design doc line 1196 (provider table): `apply_patch`, tagged **`(source)`** — read off Rust source, never exercised. Contrast `Bash`, tagged `(run)` at the same table and confirmed again at line 1048: `exec_command` normalises to `"Bash"` on the wire. | `_TOOL_OPERATIONS = {"Bash": Operation.RUN_COMMAND}` (`codex.py:92`) has no entry for whatever the edit tool's native name turns out to be, so `operation` comes back `None` for it regardless of what that name is. | **Resolved: both candidates are real, and Codex picks between them non-deterministically.** Six runs, model `gpt-6-astra`, two rounds: most edits go through `Bash` (a python heredoc, `tool_name: "Bash"`), and — confirmed by probe 4c, which forced the model toward a native edit and used a *validated* deny to prove the hook actually saw it — Codex also uses a genuine `apply_patch` tool, firing `PreToolUse` with `tool_name: "apply_patch"` literally. (The first round's reading that this second path produced no hook payload at all was wrong — see the note on §1 above; it was a malformed-envelope artefact, not evidence of an unhooked path.) **`_TOOL_OPERATIONS` has a real gap now**: `apply_patch` is not in it, so an edit taking that path still parses with `operation=None` today. Mapping it to `MODIFY_FILE` is necessary — see the F8 reconciliation below for why it's not sufficient. |
| Downstream field construction (`reads` / `edits`) | `ToolCall.edits: tuple[FileEdit, ...] = ()` and `.reads: tuple[Path, ...] = ()` (`agents/base.py:87,91`) — both default empty, populated per-adapter. | `CodexAdapter._parse_tool` never sets either field — confirmed by reading the method (`codex.py:178-191`): it returns a `ToolCall` with only `native_name`, `operation`, `command`, `raw_input` set. `edits` and `reads` are always `()` under `CodexAdapter`, independent of `tool_name`. | **Confirmed, and now the load-bearing finding rather than a side note.** `apply_patch`'s `tool_input` is `{"command": "<patch blob>"}` (§1) — the *same key* `_parse_tool` already reads for `Bash`. So even after mapping `apply_patch -> MODIFY_FILE`, `_parse_tool` would read the blob into `command` and still leave `edits`/`reads` empty, because nothing parses the blob's `*** Update File: <path>` lines into a `FileEdit`. Two fixes are needed, not one: the `_TOOL_OPERATIONS` entry, **and** a parser for the patch-blob text. Neither alone revives the five builtins gated on `tool.edits`. |
| Multi-file edits in one call | Design doc line 1009: "Codex's `apply_patch` … can touch several files in one call". Cited from the same source-only evidence as the tool name. | N/A — nothing reads `tool_input` for edits at all yet. | **Confirmed for `Bash`, untested for `apply_patch`.** Probe 3 (append `ALPHA` to `a.txt`, `BETA` to `b.txt` in the same turn) produced exactly two `PreToolUse` records for the whole turn: one discovery `rg --files` call, and one `Bash` python-heredoc call whose loop edited *both* files in a single `command` string. No probe forced a multi-file `apply_patch` call, so whether its patch-blob format concatenates multiple `*** Update File:` sections in one `command` string (plausible, given the design doc's `apply_patch` claim) or Codex always splits multi-file patches into separate hook calls is still open — lower priority than closing §4, since a parser for the single-file blob is the harder, necessary-first piece regardless. **Resolved 2026-09-16 (probe 5, `codex-cli 0.154.0`, model `gpt-5.6-sol`).** One `PreToolUse` record for the whole turn, `tool_name: apply_patch`, one blob between a single `*** Begin Patch`/`*** End Patch` pair carrying two `*** Update File:` sections, one per touched file — both files changed on disk. Codex concatenates a multi-file `apply_patch` edit into one blob; it does not split multi-file patches into separate hook calls. `_parse_patch` (shipped in #348) already parses N sections generically and carries a two-section test — nothing to change. |
| Delete spelling (`*** Delete File:`) | ADR-044's Consequences (`specs/adrs/044-codex-native-edit-path.md`): widening `FileEdit` for a delete is undecided because "the delete spelling is the patch format's, not one any probe has seen Codex emit." | N/A — `FileEdit` has no delete counterpart and nothing constructs one. | **Measured 2026-09-16 (probe 6, model `gpt-5.6-sol`).** One `PreToolUse` record, `tool_name: apply_patch`, blob is a single `*** Begin Patch`/`*** End Patch` pair with one section, literal header `*** Delete File: <abs path>` — no diff body under it. The target file was removed from disk. The spelling ADR-044 flagged as unprobed is now on record; widening `FileEdit` for it is unblocked and tracked as its own backlog item, not done here. |

## 3. Response format (verdict envelope)

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Refusal envelope, `PreToolUse` | Design doc line 408-421 and `codex.py:193-227`'s own docstring: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`, stdout, exit 0 — **observed for a `Bash` refusal**: the file the model was told to create was never created, `codex exec` echoed the reason back verbatim. | `format_hook_output` builds the identical envelope regardless of which tool triggered the hook — there is nothing tool-specific in the function, so the envelope itself is not in question. | **Resolved: the deny contract is correct for both edit paths. The first round's "no effect" reading was a test artefact, not a Codex defect.** Probe 4 (hand-escaped `echo {...}` deny verdict) let a `Bash`-mediated edit through — `target.txt` read `touched`, no block text anywhere in the transcript. Probe 4b re-ran the identical scenario with a `json.dumps`-built verdict from a file (no hand-escaping): `target.txt` stayed `untouched`, and the transcript logged `error=Command blocked by PreToolUse hook: codex-evidence probe 4b: deny-all (validated envelope). Command: pwd; rg --files ...`. Probe 4c forced a native edit and used the same validated envelope: `target.txt` stayed `untouched` again, `pre_tool_use.jsonl` recorded `tool_name: "apply_patch"`, and the transcript logged the same `Command blocked by PreToolUse hook` line, this time echoing the patch blob back as the blocked command. **Conclusion:** probe 4's malformed `echo` JSON reached Codex invalid, and per ADR-041's own documented behaviour for an unsupported/invalid `permissionDecision`, Codex **failed open** — exactly as that ADR predicts, not a new finding about Codex, a confirmation of one already on record. With a valid envelope, `deny` blocks both edit paths identically. |
| `allow` / `ask` on an edit | ADR-041 §"a hook whose verdict the agent will not honour": `allow` without `updatedInput` and `ask` are both rejected as `"unsupported permissionDecision"` and Codex **fails open** — observed for `PreToolUse`/`Bash` (`codex.py:66-71`). `_HOOK_EVENTS["pre_tool_use"].verdicts == frozenset({Verdict.DENY})` (`codex.py:81`) already encodes only `deny` as honoured, for any tool. | Same code path handles every tool identically — `format_hook_output` raises `ValueError` before emitting anything Codex hasn't been shown to honour, so there is no tool-specific branch to falsify here either. | **Not run — no longer blocking anything.** The row above closes the question this row exists to sanity-check for edits specifically (deny works, on both paths); `allow`/`ask` failing open was already established for `Bash` (`codex.py:66-71`) and there's no new reason, after confirming `deny` behaves identically across tools, to expect `allow`/`ask` to differ by tool. Worth a confirmation run only if a future change makes the harness emit `allow`/`ask` for Codex at all — nothing does today. |

## 4. State keying (hook trust)

| | Spec / design says | `CodexAdapter` assumes | Observado |
|---|---|---|---|
| Trust key shape | Design doc line 763-779: `<absolute path of declaring file>:<snake_case event>:<group index>:<handler index>` — path-scoped, **measured** on 0.154.0 with a `PreToolUse`/`Bash` hook (the byte-identical-handler probe that found `hooks.json` trusted while the identical `config.toml` declaration read `new · review required`). | `codex.py:104-109` states the choice ("hooks.json") is "frozen at the first deploy" on the strength of that same measurement — the key is derived from *event name and position in the file*, not from the tool the hook happens to guard. | **Probe 5 (lower priority — likely a non-finding).** The trust key formula names no tool at all, so an edit-triggering hook trusted the same way should behave identically. Worth one confirmation run only if Probe 1-4 raise something unexpected about how Codex treats a `PreToolUse` group whose matcher targets the edit tool specifically (e.g. a `matcher` naming `apply_patch` rather than firing unconditionally) — `_hook_groups` (`codex.py:269-295`) says an *empty* matcher was the only form observed to fire on every call; a matcher naming a specific edit tool has never been tried. |
| Matcher on a named tool | `_hook_groups`'s own docstring (`codex.py:276-281`): "An empty string was never observed, and the observed form that fires on every tool call is the one with no key at all." | The harness currently emits no per-tool matchers for Codex at all — every builtin gets an unconditional group. | **Probe 5.** If a matcher naming the edit tool's native name (from Probe 2) is tried, confirm whether Codex's matcher syntax accepts a bare tool name the way an empty matcher fires on everything, or whether it needs a different syntax (regex, glob) — this only matters once a Codex-specific hook wants to scope itself to edits alone, which nothing in the harness does yet. |

## Probes a correr

Probes 1 through 4, then 4b and 4c, all ran 2026-09-16 from an Aqua terminal,
against `codex-cli 0.154.0`, model `gpt-6-astra`; their raw output is folded
into §1-§3 above. They're kept below verbatim for reproducibility, and because
Probe 4's own malformed envelope is part of the record — it's what the F8
section below cites when explaining why the first-round reading needed
correcting. Run these from an Aqua terminal if reproducing. Each is
self-contained and creates its own disposable `CODEX_HOME`. **Do not run
`codex exec` from inside a Claude Code session** — that's the policy that
blocked the 2026-09-16 attempt before any of this, and re-hitting it from here
just burns another attempt for no new evidence.

Auth lives at `~/.codex/auth.json`; a disposable `CODEX_HOME` needs it copied in
or `codex login` run again inside it. All six probes copy it.

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

**Ran 2026-09-16. Result: `target.txt` read `touched`, deny had no observed
effect.** This script's own bug is why: its `hooks.json` built the deny verdict
with a hand-escaped `echo {...}` one-liner and never captured the raw
`PreToolUse` payload, so there was no way to tell "hook fired, verdict ignored"
from "hook never fired." Probes 4b and 4c below fix both problems and
establish it was the former: a malformed envelope, Codex failing open exactly
as ADR-041 already documents for an invalid `permissionDecision` — not a
defect in the deny contract itself.

### Probe 4b — validated deny, with payload capture

Fixes probe 4's malformed verdict (hand-escaped `echo` → `json.dumps` via a
script file, no nested shell quoting) and adds a raw-payload capture running
*before* the verdict is emitted, so the run answers "did the hook fire" and
"was deny honoured" separately instead of conflating them into one absence.

```bash
#!/usr/bin/env bash
set -euo pipefail
WORK="$(mktemp -d)"
export CODEX_HOME="$(mktemp -d)"
cp ~/.codex/auth.json "$CODEX_HOME/auth.json"

# A standalone script file, referenced by bare path — not a `-c` one-liner.
# Probe 4's hand-escaped `echo {json}` is exactly the failure mode this
# sidesteps: no nested shell/python/JSON quoting to get wrong by hand.
cat > "$CODEX_HOME/deny_hook.py" <<PY
import sys, json
open("$CODEX_HOME/pre_tool_use.jsonl", "a").write(sys.stdin.read() + "\n")
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "codex-evidence probe 4b: deny-all, validated",
    }
}))
PY

cat > "$CODEX_HOME/hooks.json" <<JSON
{
  "description": "codex-evidence probe 4b — validated deny + payload capture",
  "hooks": {
    "PreToolUse": [
      { "hooks": [ { "type": "command", "command": "python3 $CODEX_HOME/deny_hook.py" } ] }
    ]
  }
}
JSON

mkdir -p "$WORK"
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

echo "target.txt after a (validated) denied edit — must be 'untouched' if the deny worked:"
cat "$WORK/target.txt"
echo
echo "raw PreToolUse payloads captured BEFORE the deny verdict was emitted (one per line):"
cat "$CODEX_HOME/pre_tool_use.jsonl" 2>/dev/null || \
  echo "(file does not exist — the hook never fired for anything in this run, which is itself the answer to question (b))"
```

**Ran 2026-09-16. Result: `target.txt` stayed `untouched`; `pre_tool_use.jsonl`
recorded `tool_name: "Bash"`, `tool_input.command: "pwd; rg --files -g
AGENTS.md -g target.txt"`; the transcript logged `error=Command blocked by
PreToolUse hook: codex-evidence probe 4b: deny-all (validated envelope).
Command: pwd; rg --files ...`.** The deny worked. This confirms the original
probe's malformed envelope, not an unhooked path, explained the earlier
"touched" result — for the `Bash` path. Probe 4c below repeats this forcing a
native edit instead.

### Probe 4c — validated deny, forcing the native edit path

Same script as Probe 4b, with the prompt changed to steer the model away from
a shell heredoc and toward Codex's own patch tool: `"Use your native file-edit
tool (not a shell command) to change 'untouched' to 'touched' in target.txt."`
Everything else — the `deny_hook.py`, the `hooks.json`, the flags — is
identical to Probe 4b.

**Ran 2026-09-16. Result: `target.txt` stayed `untouched`; `pre_tool_use.jsonl`
recorded `tool_name: "apply_patch"`, `tool_input.command:` a raw patch blob
(`*** Begin Patch\n*** Update File: <abs path>/target.txt\n@@\n-untouched\n+touched\n*** End Patch`);
the transcript logged the same `Command blocked by PreToolUse hook` line,
echoing the patch blob as the blocked command.** The deny worked on the native
edit path too, and — the more important result — the native path **is**
gated by `PreToolUse`, firing with `tool_name: "apply_patch"`. The first
round's reading that it wasn't hooked is withdrawn; that round's deny envelope
was the same malformed one probe 4 used, so its "no block" observation never
distinguished "unhooked" from "hooked but the invalid verdict was ignored."
This run distinguishes them: hooked, and deny honoured once the verdict is
valid.

**Output → evidence cells:** §1 "`tool_input` shape for an edit" and
"`hook_event_name`", §2 "Native tool name for an edit", §3 "Refusal envelope"
— all closed by these two runs together, recorded above.

### Probes 5–8 — multi-file, delete spelling, read dialect, auth.json shape

Ran 2026-09-16 from an Aqua terminal (`probe5-7.sh`), against `codex-cli
0.154.0`, model `gpt-5.6-sol` — a different model than the six probes above
(`gpt-6-astra`); nothing below turned on the model, only on the binary. Same
fixture discipline as Probes 1-4c: a fresh, disposable `CODEX_HOME` per probe
with `auth.json` copied in and a `hooks.json` dumping every
`PreToolUse`/`PostToolUse` payload to `pre_tool_use.jsonl`; a fresh `WORK` dir
seeded with `a.txt='alpha'`, `b.txt='beta'`,
`target.txt='first line\nsecond line\nthird line'`; invoked as `codex exec
--dangerously-bypass-hook-trust --sandbox workspace-write
--skip-git-repo-check -C $WORK --json "<prompt>"`. Raw output kept at
`~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-harness/reports/codex-probes-5-8-output.txt`.

**Probe 5 — multi-file `apply_patch`.** Prompt: *"Use your built-in
file-editing tool (apply_patch), NOT the shell, to change 'alpha' to 'ALPHA'
in a.txt and 'beta' to 'BETA' in b.txt, in a single patch."*

```
#1 event=PreToolUse tool_name='apply_patch' tool_input_keys=['command']
   sections: ['*** Update File: <abs path>/a.txt', '*** Update File: <abs path>/b.txt']
   markers : ['*** Begin Patch', '*** End Patch']
files after: a.txt=ALPHA| b.txt=BETA| target.txt=first line|second line|third line|
```

One record, one blob, two `*** Update File:` sections — both files changed.
**Output → evidence cell:** §2 "Multi-file edits in one call", now resolved.

**Probe 6 — delete spelling.** Prompt: *"Use your built-in file-editing tool
(apply_patch), NOT the shell, to delete target.txt."*

```
#1 event=PreToolUse tool_name='apply_patch' tool_input_keys=['command']
   sections: ['*** Delete File: <abs path>/target.txt']
   markers : ['*** Begin Patch', '*** End Patch']
files after: a.txt=alpha| b.txt=beta| target.txt=<deleted>
```

One record, literal header `*** Delete File: <abs path>`, no diff body — the
file was removed from disk. **Output → evidence cell:** §2's new "Delete
spelling" row, above.

**Probe 7 — read dialect.** Prompt: *"Read target.txt and tell me its second
line. Do NOT use a shell command; use your built-in file-reading tool."*

```
#1 event=PreToolUse tool_name='list_mcp_resources' tool_input_keys=[]
assistant: "No built-in text-file reader is available in this session, so I
couldn't read `target.txt`. I did not use a shell command."
files after: unchanged
```

One `PreToolUse` record, `tool_name: list_mcp_resources`, empty `tool_input`,
then Codex gave up rather than fall back to `Bash` — 0.154.0 has no native
read tool. **Output → evidence cells:** §2's `pre-tool-use-read-size` row and
its ceiling note, above.

**Probe 8 — `~/.codex/auth.json` top-level shape** (keys and value types
only, no values):

```
{'auth_mode': 'str', 'OPENAI_API_KEY': 'NoneType', 'tokens': 'dict', 'last_refresh': 'str'}
```

No expiry field at the top level. The `tokens` sub-shape is unprobed — it's
what `CodexAdapter.credentials_file()` (ADR-045 D4/A4) needs before it can
return anything but `None`.

**Probe 9 (keychain entry) was not run.**

## Lo que el gate F8 ya midió y el evidence tiene que confirmar o falsificar

`specs/gates/f8/translation-gate.sh` runs entirely between two Python objects —
the shipped `ClaudeCodeAdapter` and the shipped `CodexAdapter` — and says so in
its own header (lines 88-106): *"the `codex` binary is never invoked, and the
payloads are written in Claude Code's dialect."* Concretely, its
`payload_for_operation` (line 352) feeds the *literal* Claude Code payload
`{"tool_name":"Edit","tool_input":{"file_path":"/f8/probe.py",...}}` to **both**
translators, including the one under `CodexAdapter`. That payload assumed the
exact fact this document's §2 has now confirmed is not what happens: Codex's
real wire `tool_name` for an edit is `"Bash"` **or** `"apply_patch"`, the
model's own non-deterministic choice, never `"Edit"`. The gate's own inputs
never exercised either real case — it measured "what happens if Codex sent
Claude's tool name," not "what Codex actually sends."

**Measured 2026-09-16, by reading the code, confirmed above in §2:**
`CodexAdapter._parse_tool` (`codex.py:178-191`) never populates `ToolCall.edits`
or `.reads` for *any* tool name — those fields default to `()` and nothing in
the method sets them. This is why the ADR's account needed correcting: the
`operation` gate is the *first* of two, not the only one. **Resolved against
the real binary, 2026-09-16, across two probe rounds**: Codex takes two
edit paths, `Bash` (most runs) and `apply_patch` (confirmed real and hooked
only once probe 4c used a validated deny — the first round's read of
`apply_patch` as unhooked was itself a malformed-envelope artefact, see §1/§3).
The two-guard analysis below covers both paths.

Per builtin, the two guards it actually hits under `CodexAdapter` today:

| Builtin | First guard | Result on `Bash` | Result on `apply_patch` | Second guard | Result |
|---|---|---|---|---|---|
| `post-tool-use-format` | `tool.operation is not Operation.MODIFY_FILE` (`post_tool_use_format.py:32`) | Fails: `operation` is `RUN_COMMAND`, never `MODIFY_FILE`. | Fails **today**: `operation` is `None` — `apply_patch` isn't in `_TOOL_OPERATIONS` at all. Mapping it to `MODIFY_FILE` would flip this guard to pass. | `for edit in tool.edits` (`post_tool_use_format.py:36`) | Never reached on either path today. If `apply_patch` were mapped, this becomes reachable and still fails: `tool.edits` is `()` regardless of `operation`, because `_parse_tool` never parses the patch blob (§2). |
| `pre-tool-use-read-size` | `tool.operation is not Operation.READ_FILE` (`pre_tool_use_read_size.py:105`) | Fails: `RUN_COMMAND`, never `READ_FILE`. | Fails: `None`, and would still fail even mapped — `apply_patch` is an edit, not a read; `READ_FILE` is the wrong target operation for it regardless. | `for path in tool.reads` (`pre_tool_use_read_size.py:119`) | Never reached, and mapping `apply_patch` doesn't change that — this hook was never going to apply to an edit tool. **Probe 7, 2026-09-16 (model `gpt-5.6-sol`): confirmed inert for a different reason than assumed.** Asked for a native read, Codex fired `PreToolUse` with `tool_name: list_mcp_resources`, empty `tool_input`, then told the model no built-in text-file reader is available in this session — 0.154.0 has no native read tool at all. Reads go through `Bash` (`cat`/`sed`/`rg`), the same structurally-ungateable path this document already records for edits. |
| `pre-tool-use-memory-size` | `tool.native_name not in INSPECTED_TOOLS` where `INSPECTED_TOOLS = {"Edit", "Write"}` (`pre_tool_use_memory_size.py:44,225`) | Fails: `native_name == "Bash"`, never in the set. | **Fails today, confirmed by run**: `native_name == "apply_patch"`, and `"apply_patch"` is not in `{"Edit","Write"}` either — the set itself needs widening, separately from `_TOOL_OPERATIONS`. | `for edit in tool.edits` (`pre_tool_use_memory_size.py:234`) | Never reached on either path today. If both the set *and* `_TOOL_OPERATIONS` were fixed, still fails: `tool.edits` stays `()` until the patch blob is parsed. |
| `post-tool-use-sync-claude` | Same `INSPECTED_TOOLS` check (`post_tool_use_sync_claude.py:32,76`) | Fails: `"Bash"` not in the set. | Fails: `"apply_patch"` not in the set. | `tuple(edit.path for edit in tool.edits)` (`post_tool_use_sync_claude.py:78`) | Never reached; same blob-parsing gap blocks it even if the set and the mapping were both fixed. |
| `post-tool-use-ansible-lint` | Same `INSPECTED_TOOLS` check (`post_tool_use_ansible_lint.py:33,113`) | Fails: `"Bash"` not in the set. | Fails: `"apply_patch"` not in the set. | `for edit in tool.edits` (`post_tool_use_ansible_lint.py:122`) | Never reached; same blob-parsing gap. |

**Corrected conclusion: two fixes are required, and neither alone is
sufficient — sharper, and more pessimistic, than the ADR's original "widening
`_TOOL_OPERATIONS` is a no-op."** That framing implied one missing mapping was
the whole defect. It isn't. Two independent gaps stack:

1. **`_TOOL_OPERATIONS` has no entry for `apply_patch`**, so it parses with
   `operation=None` today — necessary to fix for `post-tool-use-format` and
   `pre-tool-use-read-size` to even have a chance (and `pre-tool-use-read-size`
   still wouldn't apply, being about reads, not edits). `INSPECTED_TOOLS =
   {"Edit", "Write"}` separately has no entry for `"apply_patch"` either — a
   second, independent set that gates the other three builtins and needs its
   own widening.
2. **Even with both of those fixed, `_parse_tool` still never parses
   `apply_patch`'s `tool_input.command` into a `FileEdit`.** The value under
   `command` is patch *text* — `*** Begin Patch\n*** Update File: <path>\n@@\n...\n*** End Patch`
   — not a structured field. `tool.edits` stays `()` until something parses the
   `*** Update File: <path>` lines out of that blob. Mapping the operation and
   widening the tool-name set are both necessary and both insufficient on
   their own: every one of the five builtins gated on `tool.edits` needs the
   parser too.

**Correction, 2026-09-16, after #348.** Shipping the fixes above found one
more, absent from this reconciliation: `pre_tool_use_memory_size._projected_text`
branches on the *tool name* — `"Write"` takes `content`, `"Edit"` replays
`replacements`, anything else falls through to `None` and the hook goes quiet.
`apply_patch` carries both shapes in one blob, so it is the one tool whose
branch is chosen by the `FileEdit` it carries, not by its name. With
`_TOOL_OPERATIONS`, `INSPECTED_TOOLS` and the patch parser all in place, this
builtin still stayed silent — a fourth fix, not the three implied above.
Closed in #348; `specs/backlog.md` §Done has the record.

**`pre-tool-use-read-size`'s inertness is now a measured design limit, not an
open question.** Probe 7 (2026-09-16, model `gpt-5.6-sol`) asked Codex for a
native read and it fired `PreToolUse` with `tool_name: list_mcp_resources`,
empty `tool_input`, then answered that no built-in text-file reader is
available in this session. Codex 0.154.0 has no native read tool at all —
reads go through `Bash` (`cat`/`sed`/`rg`), the same tool this document
already records as structurally ungateable for edits. ADR-044 §2 left this
builtin un-widened on the assumption that `apply_patch` is an edit, not a
read; the deeper reason it stays inert is now on record — there is no read
dialect under Codex to gate, full stop.

**The `Bash` path is structurally different, not just currently unmapped: it
cannot be gated as an edit at all with information the hook has.** `tool_input`
for a `Bash`-mediated edit is `{"command": "<arbitrary shell script>"}` — there
is no reliable path to extract, because the model can construct that script
however it likes (the observed heredoc is one shape among unbounded others).
Mapping `Bash` to `MODIFY_FILE` when its `command` merely *happens* to write a
file would be wrong for the same reason `RUN_COMMAND` is the correct
`operation` for it today: from the hook's point of view a `Bash` call is a
command, not a structured edit, regardless of what that command does. **Net
effect for the harness**: Codex's model chooses non-deterministically between
an edit path that's parseable in principle (`apply_patch`, pending the two
fixes above) and one that structurally isn't (`Bash`). Even a fully-fixed
adapter would only gate half of Codex's edits — the other half arrives as an
opaque shell command indistinguishable, at the hook layer, from any other
`Bash` call.

**This sharpens the F8 gate's own finding rather than reversing it.**
`translation-gate.sh` feeds every translator the literal payload
`{"tool_name":"Edit",...}` (line 352) — Claude Code's dialect, neither of
Codex's two real ones. Under that synthetic input, the `INSPECTED_TOOLS` check
*passes* (the gate told the Codex translator the tool was called `"Edit"`), so
the gate's inert verdict for those three builtins is produced entirely by the
second guard, `tool.edits` being empty, exactly as its own comments say.
Against the real binary the verdict is the same — inert — but for a guard
combination the gate's synthetic payload never exercised: the real `apply_patch`
payload fails at *both* guards today (tool-name set, then blob parsing), and
the real `Bash` payload was never a candidate for gating as an edit regardless
of either guard. F8's header names this precisely: it measures "the shipped
adapter pair," two Python objects, and explicitly disclaims knowing anything
about the binary. That isn't a defect in F8 — it's the exact gap this document
exists to close, and it's now closed with a sharper, two-part diagnosis than
either F8 or the original ADR account gave.

## Corrección al design doc padre

`specs/designs/2026-09-13-multi-agent-harness-design.md`'s provider table
(line 1196) listed Codex's native tool names as `apply_patch, shell (source)`
— both tagged as read off source, never run. Both are now confirmed real
by run, elevated from `(source)` to `(run, 0.154.0)`: Codex takes both paths,
the model's own non-deterministic choice, and both fire `PreToolUse` (`Bash`
with `tool_name: "Bash"`, `apply_patch` with `tool_name: "apply_patch"` and a
raw patch-text blob under `tool_input.command`). The design doc's own
claims-correction table (lines 90-97, "Where the convergence stops") is where
this repo records exactly this kind of update; the row added there for this
document is updated in place to reflect the corrected, two-path finding rather
than the first round's now-withdrawn "`file_change` looked unhooked" reading,
and the provider table's Codex cell is updated the same way. Nothing else in
that document is touched — the architecture decisions built on "plural
`edits`/`reads` because an edit can touch several files" (line 1009) still
hold: probe 3 confirms multi-file edits happen in one hook call for `Bash`,
and nothing here contradicts the same being possible for `apply_patch`
(untested, §2).

**Update, probe 5 (2026-09-16, above): the "untested" just above is now
resolved.** `apply_patch` concatenates a multi-file edit into one blob with
multiple `*** Update File:` sections rather than splitting across hook calls —
confirmed in §2's "Multi-file edits in one call" row.

**A third tool_name surfaced, outside the two-path pair above.** Probe 7
(§2's `pre-tool-use-read-size` row, below) fired `PreToolUse` with
`tool_name: list_mcp_resources` and an empty `tool_input` (`{}`) when asked
for a native read — not an edit tool, and not added to the provider table's
edit-path list, but the concrete evidence behind "Codex has no native read
tool at 0.154.0."

## 5. Rollout format (transcript on disk)

**Medido** el 2026-09-16 sobre los rollouts que `codex-cli 0.154.0` escribió en
esta máquina: 15 archivos, 1.147 líneas, 0 no parseables, todos con
`session_meta.cli_version == "0.154.0"`. `[log], 0.154.0` — leídos del disco, no
corridos contra el binario. Un schema de transcript vale sólo para la versión en
la que se observó (design doc `:1901-1905`), así que la versión queda anotada acá
y en el docstring del reader, y **no** hay switch de versiones: nunca existió una
segunda.

Nada del contenido de esas sesiones entra al repo. Lo que sigue es forma —
claves, anidamiento, tipos, inventario de kinds y conteos. Los fixtures de
`tests/unit/test_agent_codex_transcript.py` son sintéticos, reconstruidos desde
esta tabla.

### 5.1 Envelope

Una línea = un objeto JSON con exactamente cuatro claves, en 416/416 líneas del
día medido:

| Clave | Tipo | Observado |
|---|---|---|
| `timestamp` | `str` | ISO-8601 UTC con milisegundos y sufijo `Z`: `2026-09-16T12:02:13.926Z` (24 chars). `datetime.fromisoformat` lo acepta desde 3.11. |
| `type` | `str` | El kind de nivel superior — seis valores, tabla 5.2. |
| `payload` | `dict` | El cuerpo. Para `event_msg` y `response_item` lleva su propio `payload.type`; para los otros cuatro, no. |
| `ordinal` | `int` | Índice creciente dentro del archivo. |

**Ruta y nombre:** `$CODEX_HOME/sessions/<YYYY>/<MM>/<DD>/rollout-<YYYY-MM-DD>T<HH-MM-SS>-<uuid v7>.jsonl`.
El stamp del nombre es el **arranque de la sesión en hora local, sin offset**:
`rollout-2026-09-16T09-02-04-...` cuya primera línea es
`2026-09-16T12:02:13.926Z` — tres horas de diferencia en un host UTC-3. No es
hora de modificación ni UTC; ver ADR-048 para por qué `locate_sessions` filtra
por mtime y no por el nombre.

### 5.2 Inventario de kinds

Los 15 archivos, `type` (+ `payload.type` donde existe):

| Kind | Líneas | Señal que entrega | Leído |
|---|---|---|---|
| `event_msg/item_completed` | 441 | — (duplica lo de abajo) | no |
| `event_msg/token_count` | 179 | duplica `token_usage_record` | no |
| `token_usage_record` | 176 | `TOKEN_USAGE` | **sí** |
| `response_item/custom_tool_call` | 154 | `TOOL_CALLS` | **sí** |
| `response_item/custom_tool_call_output` | 154 | — (resultado, no llamada) | no |
| `response_item/message` | 151 | `MESSAGES` (roles `user`/`assistant`) | **sí** |
| `response_item/reasoning` | 134 | — (`encrypted_content`, no es texto que alguien vio) | no |
| `event_msg/task_started` | 23 | — | no |
| `event_msg/task_complete` | 23 | — | no |
| `turn_context` | 23 | — (cwd, modelo, sandbox, permisos) | no |
| `world_state` | 18 | — (instrucciones compuestas del turno) | no |
| `session_meta` | 15 | — (`cli_version`, `cwd`, `git`, `id`) | no |
| `event_msg/thread_settings_applied` | 8 | — | no |
| `response_item/function_call` | 2 | `TOOL_CALLS` | **sí** |
| `response_item/function_call_output` | 2 | — | no |

**No hay ningún kind, ni ningún campo de payload, que marque un objetivo
explícito.** Codex 0.154.0 no tiene `/goal` y el rollout no lleva nada
equivalente: `GOAL_STATUS` no se entrega, y `signals()` no lo declara.

### 5.3 Los tres streams que se leen

**`response_item/message`** — `{type, id, role, content[], phase?, internal_chat_message_metadata_passthrough}`.
`role` ∈ `{assistant: 67, developer: 46, user: 38}`. `content[]` son bloques
`{type, text}` con `type` ∈ `{input_text: 135, output_text: 67}` — `input_text`
en turnos `user`/`developer`, `output_text` en `assistant`. No hay string pelado
en `content` (a diferencia de Claude Code). `developer` es el canal de
instrucciones compuestas, no un turno de nadie: no se emite (ADR-048).

**`response_item/custom_tool_call`** — `{type, id, call_id, name, input, status}`.
`name` == `exec` en 154/154 llamadas. `status` == `completed`. **`input` es un
`str` que no es JSON y no es shell**: 154/154 multilínea, 154/154 contienen
`await `, 154/154 contienen `;`, 70 contienen `const `; primeras palabras
`text` (81), `const` (64), `for` (6), `await` (3). Es un programa para el
runtime de celdas de Codex (`unified_exec`), no un comando. Por eso no se mapea
a `ToolCall.command` (ADR-048).

**`response_item/function_call`** — `{type, id, call_id, name, arguments}`.
`name` == `wait` en 2/2; `arguments` sí es JSON, con claves
`{cell_id, max_tokens, yield_time_ms}` — el otro extremo del mismo runtime de
celdas.

**`token_usage_record`** — `{session_id, thread_id, turn_id, root_turn_id, response_id, usage, turn_token_usage, thread_token_usage}`.
Los tres objetos de usage tienen forma idéntica:
`{input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens, total_tokens}`, todos `int`. `usage` y
`turn_token_usage` fueron iguales en cada línea medida; `thread_token_usage` es
el acumulado de la sesión. Mapeo a `TokenUsage`:
`input_tokens→input_tokens`, `output_tokens→output_tokens`,
`cached_input_tokens→cache_read_tokens`,
`cache_write_input_tokens→cache_creation_tokens`.
`reasoning_output_tokens` y `total_tokens` no tienen campo y no se suman a
ninguno.

### 5.4 Lo que el stream `event_msg` duplica

`event_msg/item_completed` lleva `{completed_at_ms, started_at_ms, thread_id, turn_id, item}`
y `item.type` ∈ `{CommandExecution: 211, Reasoning, AgentMessage, UserMessage, Extension, FileChange}`.
Es la vista de la TUI del mismo turno que el stream `response_item` ya registró,
y no lleva `call_id`. Se descarta entero para no contar dos veces (ADR-048).

`item.type == "CommandExecution"` es igualmente la **única** grafía donde aparece
el comando realmente ejecutado: `command` es una lista de 3 elementos, siempre
`["/bin/zsh", "-lc", "<script>"]`, con `cwd`, `exit_code`, `status`
(`completed: 193`, `failed: 18`), `duration{secs,nanos}`, `process_id` y
`parsed_cmd[]` (tipos `read: 231`, `unknown: 129`, `search: 58`,
`list_files: 12`). `source` == `unified_exec_startup` en 211/211.

### 5.5 Lo que no se observó, y por lo tanto no se declara

- **`apply_patch` como tool call del rollout: 0 ocurrencias** en 154 llamadas y
  15 sesiones. En este modo las ediciones las hace el programa `exec`, y la
  única línea que nombra los archivos tocados es
  `item_completed/FileChange` (3 ocurrencias), cuyo `changes` es un dict
  **tecleado por path absoluto** → `{type, content}`. No se emite: no tiene
  `call_id`, pertenece al stream duplicado, y `_parse_patch` no tiene entrada
  acá. El día que un rollout traiga un `custom_tool_call` llamado
  `apply_patch`, el mapeo a `{"command": input}` es una línea y un test.
- **Un segundo `cli_version`.** 15/15 archivos dicen `0.154.0`.
- **`GOAL_STATUS`**, por 5.2.

## Pendiente

Cerrado 2026-09-16 contra el binario real (`codex-cli 0.154.0`, modelo
`gpt-6-astra`, seis corridas desde Aqua en dos rondas): §1, §2, §3, y la tabla
de reconciliación F8 completa. El primer round (probes 1-4) dejó una lectura
equivocada en §2/§3 — un envelope de deny malformado hizo que Codex fallara
abierto, lo que se leyó como "el path nativo no está hookeado"; el segundo
round (probes 4b y 4c, envelope validado con `json.dumps`) la corrigió: el
deny funciona en los dos paths, y `apply_patch` SÍ dispara `PreToolUse` con
`tool_name: "apply_patch"`. Esa corrección se reflejó también en el design doc
padre (`specs/designs/2026-09-13-multi-agent-harness-design.md`, tabla de
claims y tabla de providers).

**§5 (Rollout format) se agregó después y también está cerrada** — medida el
2026-09-16 contra los mismos 15 rollouts de `codex-cli 0.154.0` (step 12, PR
#355), fuera del alcance de las seis corridas de arriba.

**Conclusión F8, cerrada:** mapear `apply_patch -> MODIFY_FILE` en
`_TOOL_OPERATIONS` es necesario pero no suficiente — hace falta además sumar
`"apply_patch"` a `INSPECTED_TOOLS` y, más importante, parsear el blob de patch
(`*** Update File: <path>`) en `FileEdit`s reales, porque `_parse_tool` nunca
lo hace hoy. El path `Bash` es estructuralmente no-gateable como edit,
independiente de cualquier mapeo: es un comando de shell arbitrario, sin campo
de path que extraer.

**No ejercitado por estas corridas:** §4 (state keying) — ninguno de los seis
probes tocó trust ni matchers, y queda con el alcance original documentado ahí.
`allow`/`ask` sobre un edit tampoco se corrió — de menor prioridad ahora que el
contrato de `deny` quedó confirmado en los dos paths, y sin usarse hoy en el
harness para Codex.

**Cerrado además el 2026-09-16, probes 5-8 (`probe5-7.sh`, mismo binario,
modelo `gpt-5.6-sol`):** multi-file `apply_patch` (probe 5, dos secciones
`*** Update File:` en un solo blob), la grafía de delete (probe 6, `*** Delete
File: <path>` literal, sin diff body) y el dialecto de lectura (probe 7,
`list_mcp_resources` con `tool_input` vacío, sin reader nativo) — las tres
preguntas que quedaban abiertas en §2 arriba. `pre-tool-use-read-size` pasa de
"sin ejercitar" a límite estructural medido, en la misma clase que el path
`Bash`. Probe 8 midió además la forma de nivel superior de
`~/.codex/auth.json` (`auth_mode`, `OPENAI_API_KEY`, `tokens`,
`last_refresh`) — ver `specs/backlog.md` y ADR-045 para el uso de ese
hallazgo.

**Sigue sin correr:** la sub-forma de `tokens` dentro de `auth.json`, y la
probe 9 (keychain, ADR-045 A5) — no se corre desde un pane de agente.
