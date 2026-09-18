#!/usr/bin/env bash
# Copilot CLI 1.0.83 — the probe that closes `specs/designs/copilot-evidence.md`.
#
# RUN THIS FROM AN AQUA TERMINAL. Never from a Claude Code or Herdr pane: this
# repo's standing rule for agent binaries, and the one that blocked the Codex
# probes on 2026-09-16 before they ran. It drives `copilot`, which authenticates.
#
#   bash specs/gates/probes/copilot-probe1.sh
#
# WHAT IT MEASURES, in four phases, each in its own disposable `COPILOT_HOME`.
# The order is a dependency chain, not a preference:
#
#   0  DOCUMENT SHAPE. Which `$COPILOT_HOME/hooks/*.json` shapes the binary
#      loads. Everything below is meaningless until one does, and the shape
#      `CopilotAdapter.plan_config` writes today is read out of the strings in
#      `prebuilds/darwin-arm64/runtime.node` — [src], never a load.
#   1  PAYLOAD. One sink per accepted event, one prompt that forces a shell
#      command, a file read, a file edit and a failing command.
#   2  RESPONSE ENVELOPE. The verdicts and channels the adapter does NOT emit,
#      varied one at a time against a fixed control.
#   3  SYSTEM DOCS. Which user-level instruction destination Copilot loads.
#
# WHY A PROBE THAT VARIES NOTHING IS A PROBE OF ONE INPUT. This is the design's
# own gate, added after the `hookSpecificOutput` reading was recorded wrong
# twice (`specs/designs/2026-09-13-multi-agent-harness-design.md:2160-2172`):
# each earlier pass ran ONE envelope and generalised to "JSON verdicts". Every
# phase below therefore enumerates its class and keeps a control in it.
#
# NO AUTH COPYING, and that is a finding rather than an omission. The design
# records that every deny-matrix run used a throwaway `COPILOT_HOME` and auth
# survived it (`:1195`, run, 1.0.83) — so the credential is not under
# `COPILOT_HOME`, which is exactly why `CopilotAdapter.credentials_file()`
# returns `None`. If a phase below stops at a login prompt, that row is wrong
# and the adapter's docstring has to change with it.
#
# THE SUMMARY PRINTS KEYS AND TYPES, NEVER BODIES. `copilot_probe_summary.py`
# beside this file does that half, and `tests/unit/test_copilot_probe_summary.py`
# asserts it: payloads carry prompts, commands and paths, and this output is
# meant to be pasted into a file in a public repository.

set -euo pipefail

BIN="${COPILOT_BIN:-copilot}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMARY="$HERE/copilot_probe_summary.py"
OUT="${PROBE_OUT:-$(mktemp -d)}"
MARKER="copilot-probe-$$"

command -v "$BIN" >/dev/null 2>&1 || { echo "no '$BIN' on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "no python3 on PATH" >&2; exit 2; }
[ -f "$SUMMARY" ] || { echo "missing summary printer: $SUMMARY" >&2; exit 2; }

echo "probe output: $OUT"
echo "binary:       $("$BIN" --version 2>&1 | head -1)"
echo

# The eleven names 1.0.83 accepts, established by rejection, not by `strings`
# (`specs/designs/2026-09-13-multi-agent-harness-design.md:1199`, run). The five
# it drops — userPromptSubmit, postCompact, stop, error, preResponse — are NOT
# registered here: a run that registers them re-measures a closed question and
# buries the eleven under `Ignoring unknown hook event(s)`.
EVENTS=(
  preToolUse postToolUse postToolUseFailure preMcpToolCall permissionRequest
  sessionStart sessionEnd preCompact notification subagentStart subagentStop
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A fresh home with a `hooks/` directory and a payload sink directory.
new_home() {
  local home
  home="$(mktemp -d)"
  mkdir -p "$home/hooks" "$home/probe"
  printf '%s' "$home"
}

# A workspace with the fixtures phase 1's prompt reads, edits and fails on.
new_work() {
  local work
  work="$(mktemp -d)"
  printf 'untouched\n' > "$work/fixture.txt"
  printf '%s\n' "$MARKER" > "$work/readme.txt"
  printf '%s' "$work"
}

# The hook document, built by python3 rather than by hand.
#
# Hand-escaped JSON is not a style preference here: the first round of the Codex
# probes built a deny verdict with an `echo` one-liner, produced a malformed
# envelope, and recorded "the hook did not fire" for what was actually "the
# verdict did not parse" (`specs/designs/codex-evidence.md` §3). One `json.dumps`
# removes that whole class of misreading.
#
#   $1  destination file
#   $2  shape: flat-command | nested-hooks | no-version | bash-key | extra-key
#   $3  sink directory
#   $4… event names to register
write_hook_doc() {
  local dest="$1" shape="$2" sink="$3"
  shift 3
  DEST="$dest" SHAPE="$shape" SINK="$sink" EVENTS="$*" python3 - <<'PY'
import json
import os

dest = os.environ["DEST"]
shape = os.environ["SHAPE"]
sink = os.environ["SINK"]
events = os.environ["EVENTS"].split()

def handler(event: str) -> str:
    # `cat` appends the raw payload and exits 0 with no stdout at all, which is
    # the "no verdict" case. An `echo` here would put an empty line on the
    # channel Copilot reads verdicts from, and an empty line is a parse the
    # probe has no reason to ask about.
    return f'/bin/sh -c "cat >> {sink}/{event}.jsonl"'

hooks: dict[str, list[dict]] = {}
for event in events:
    if shape == "nested-hooks":
        # The Claude Code / Codex grouping. `Nested hooks deeper than one level
        # are not supported.` is in the runtime's strings, so one level may be
        # exactly what this is.
        entry: dict = {"hooks": [{"type": "command", "command": handler(event)}]}
    elif shape == "bash-key":
        # `Specify either 'exec' (native executable) or 'bash'/'powershell'/
        # 'command' (shell), but not both` — so `bash` is a sibling spelling.
        entry = {"bash": handler(event)}
    else:
        entry = {"command": handler(event)}
    hooks[event] = [entry]

document: dict = {"version": 1, "hooks": hooks}
if shape == "no-version":
    # `version: Required` is a string in the runtime. This is the run that says
    # whether it is enforced on this path.
    document.pop("version")
if shape == "extra-key":
    # Whether an unknown top-level key survives is what a `description`
    # ownership stamp would need — `CodexAdapter` has one, and `CopilotAdapter`
    # owns its filename instead precisely because this is unmeasured.
    document["description"] = "lazy-harness probe"

with open(dest, "w", encoding="utf-8") as handle:
    json.dump(document, handle, indent=2)
    handle.write("\n")
PY
}

# Drive one non-interactive run. Never fails the script: a refused or errored
# run is an observation, and `set -e` would throw it away.
drive() {
  local home="$1" work="$2" prompt="$3" log="$4"
  ( cd "$work" && COPILOT_HOME="$home" "$BIN" -p "$prompt" --allow-all-tools ) \
    > "$log.stdout" 2> "$log.stderr" || echo "exit=$?" >> "$log.stderr"
}

# Everything the runtime said about loading the document, which is where a
# rejected shape announces itself.
loader_diagnostics() {
  local home="$1" log="$2"
  {
    grep -hiE 'hook|schema|Expected|Required|Invalid|Ignoring' "$log.stdout" "$log.stderr" 2>/dev/null || true
    find "$home/logs" -type f -exec grep -hiE 'hook' {} + 2>/dev/null || true
  } | sort -u | head -40
}

# ---------------------------------------------------------------------------
# Phase 0 — which document shape loads AND fires
# ---------------------------------------------------------------------------
# Two questions, not one, and conflating them is how `_vsCodeCompat` looked
# tolerant when it was merely unread (`:2093-2099`): a document can load with no
# diagnostic and still register nothing. The discriminator is the sink file.

echo "== phase 0: hook document shape =="
WORKING_SHAPE=""
for shape in flat-command nested-hooks bash-key no-version extra-key; do
  home="$(new_home)"; work="$(new_work)"
  write_hook_doc "$home/hooks/probe.json" "$shape" "$home/probe" preToolUse
  drive "$home" "$work" "Run the shell command: echo $MARKER" "$OUT/phase0-$shape"

  fired="no"
  [ -s "$home/probe/preToolUse.jsonl" ] && fired="yes"
  echo "  $shape: fired=$fired"
  loader_diagnostics "$home" "$OUT/phase0-$shape" | sed 's/^/      /'
  cp -R "$home/probe" "$OUT/phase0-$shape.sinks" 2>/dev/null || true

  if [ "$fired" = yes ] && [ -z "$WORKING_SHAPE" ]; then
    WORKING_SHAPE="$shape"
  fi
done

if [ -z "$WORKING_SHAPE" ]; then
  echo
  echo "NO SHAPE FIRED. Stop here and record that in copilot-evidence.md §4 —"
  echo "it means CopilotAdapter.plan_config writes a document Copilot ignores,"
  echo "which is a shipped defect, not a gap. Phases 1-3 would measure nothing."
  exit 1
fi
echo "  -> using shape: $WORKING_SHAPE"
echo

# ---------------------------------------------------------------------------
# Phase 1 — one payload per accepted event
# ---------------------------------------------------------------------------
# The prompt forces four things on purpose: a shell command (`bash`, the one
# tool whose arguments are already measured — it is the control), a file read
# (`view`, whose argument key is unmeasured and which the adapter maps to
# READ_FILE with nothing in `reads`), a file edit (the tool that has NEVER been
# observed — the largest single gap in the adapter), and a failing command
# (`postToolUseFailure`, which fires for `failure` results only).

echo "== phase 1: payloads for all eleven events =="
home="$(new_home)"; work="$(new_work)"
write_hook_doc "$home/hooks/probe.json" "$WORKING_SHAPE" "$home/probe" "${EVENTS[@]}"
drive "$home" "$work" \
  "Do these four things in order, in the current directory, and nothing else. \
1. Run the shell command: echo $MARKER. \
2. Read the file readme.txt and tell me its first line. \
3. Change the word untouched to touched in fixture.txt. \
4. Run the shell command: false" \
  "$OUT/phase1"

cp -R "$home/probe" "$OUT/phase1.sinks"
echo "  fixture.txt now reads: $(head -1 "$work/fixture.txt")"
echo "  (that line answers whether the edit happened at all — a payload sink"
echo "   with no edit tool in it means something different if it did not)"
echo
python3 "$SUMMARY" "$home/probe"

for event in "${EVENTS[@]}"; do
  [ -s "$home/probe/$event.jsonl" ] || echo "  $event: no sink — not fired this run"
done
echo

# ---------------------------------------------------------------------------
# Phase 2 — the response envelope, one variable at a time
# ---------------------------------------------------------------------------
# Every row here is a channel `CopilotAdapter.format_hook_output` refuses to
# emit today because no run has shown it being read. `deny` is the CONTROL: it
# is measured, it must block, and a run where it does not means the phase is
# broken rather than the rows being negative.

echo "== phase 2: response envelope =="
CONTEXT_NONCE="ctx-$MARKER"
for verdict in control-deny allow ask additional-context suppress-output system-message; do
  home="$(new_home)"; work="$(new_work)"
  case "$verdict" in
    control-deny)       body='{"permissionDecision":"deny","permissionDecisionReason":"probe control"}' ;;
    allow)              body='{"permissionDecision":"allow","permissionDecisionReason":"probe"}' ;;
    ask)                body='{"permissionDecision":"ask","permissionDecisionReason":"probe"}' ;;
    additional-context) body="{\"additionalContext\":\"$CONTEXT_NONCE\"}" ;;
    suppress-output)    body='{"suppressOutput":true}' ;;
    system-message)     body="{\"systemMessage\":\"$CONTEXT_NONCE\"}" ;;
  esac

  # A handler that prints one fixed line and exits 0. The stdin is still
  # captured, so "the verdict was ignored" stays distinguishable from "the hook
  # never fired" — the control the deny matrix needed and the first two
  # readings of it lacked.
  printf '#!/bin/sh\ncat >> "%s/preToolUse.jsonl"\nprintf %%s %s\n' \
    "$home/probe" "'$body'" > "$home/verdict.sh"
  chmod +x "$home/verdict.sh"
  python3 - "$home/hooks/probe.json" "$home/verdict.sh" "$WORKING_SHAPE" <<'PY'
import json
import sys

dest, script, shape = sys.argv[1:4]
entry = (
    {"hooks": [{"type": "command", "command": script}]}
    if shape == "nested-hooks"
    else ({"bash": script} if shape == "bash-key" else {"command": script})
)
document = {"version": 1, "hooks": {"preToolUse": [entry]}}
if shape == "no-version":
    document.pop("version")
with open(dest, "w", encoding="utf-8") as handle:
    json.dump(document, handle, indent=2)
PY

  drive "$home" "$work" \
    "Run the shell command: echo $MARKER. Then repeat back, verbatim, any extra \
context or system message you were given during this turn." \
    "$OUT/phase2-$verdict"

  ran="no";  grep -q "$MARKER" "$OUT/phase2-$verdict.stdout" 2>/dev/null && ran="yes"
  fired="no"; [ -s "$home/probe/preToolUse.jsonl" ] && fired="yes"
  echoed="no"; grep -q "$CONTEXT_NONCE" "$OUT/phase2-$verdict.stdout" 2>/dev/null && echoed="yes"
  echo "  $verdict: hook_fired=$fired command_ran=$ran nonce_reached_model=$echoed"
done
echo "  (control-deny must show command_ran=no. If it does not, phase 2 is"
echo "   broken and its negatives say nothing.)"
echo

# ---------------------------------------------------------------------------
# Phase 3 — which system-doc destination Copilot actually loads
# ---------------------------------------------------------------------------
# The row step 11 exists for. `system_docs()` returns `copilot-instructions.md`
# on **vendor docs alone** (`:1197`), deliberately left weak by the design's own
# 2026-09-14 sweep: never exercised. `instructions/**/*.instructions.md` is the
# second claimed destination, and `system_docs()` promises the agent loads every
# entry it returns — so shipping both would be an assertion nothing has tested.

echo "== phase 3: system_docs destinations =="
home="$(new_home)"; work="$(new_work)"
mkdir -p "$home/instructions"
printf 'The secret word for FLAT is %s-flat.\n' "$MARKER" > "$home/copilot-instructions.md"
printf 'The secret word for NESTED is %s-nested.\n' "$MARKER" \
  > "$home/instructions/probe.instructions.md"
drive "$home" "$work" \
  "State the secret word for FLAT and the secret word for NESTED. If you were \
not told one of them, say NOT GIVEN for it." "$OUT/phase3"

flat="no";   grep -q "$MARKER-flat"   "$OUT/phase3.stdout" 2>/dev/null && flat="yes"
nested="no"; grep -q "$MARKER-nested" "$OUT/phase3.stdout" 2>/dev/null && nested="yes"
echo "  copilot-instructions.md loaded:              $flat"
echo "  instructions/*.instructions.md loaded:       $nested"
echo "  (both yes -> system_docs() may return two destinations; flat only ->"
echo "   the shipped one-entry answer is correct; neither -> the vendor-docs"
echo "   row is wrong and sync_agent_md writes into a void)"
echo

# ---------------------------------------------------------------------------

cat <<EOF
== done ==

Artifacts under: $OUT

Paste into specs/designs/copilot-evidence.md:
  §1  the phase 1 summary block (keys and types)
  §2  the phase 1 summary's toolArgs rows, plus the edit tool's name if one
      appeared at all
  §3  the phase 2 table
  §4  the phase 0 table
  §5  the phase 3 result

Then reopen ADR-047's Consequences against what it says: every row that moves
from a probe to a measurement either unblocks a builtin or confirms it inert,
and the ADR names both lists.
EOF
