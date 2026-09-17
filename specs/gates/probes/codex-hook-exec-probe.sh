#!/usr/bin/env bash
# Codex CLI 0.154.0 — why does a matched PreToolUse group not block the call?
#
# RUN THIS FROM A PLAIN TERMINAL. Never from a Claude Code or Herdr pane: this
# repo's standing rule for agent binaries. It drives `codex exec`, which
# authenticates and executes model-proposed shell commands.
#
#   bash specs/gates/probes/codex-hook-exec-probe.sh
#   bash specs/gates/probes/codex-hook-exec-probe.sh --dry-run   # renders, spawns nothing
#
# WHAT IS ALREADY MEASURED, AND WHY THAT LEAVES EXACTLY ONE QUESTION.
#
#   * `codex-matcher-probe.sh` (2026-09-17 13:22) FALSIFIED H1 and H3. Codex
#     honours `PreToolUse` matchers, evaluates every group rather than stopping
#     at the first match, and matches `Bash|Read|Edit|Write|NotebookEdit` — the
#     literal guarding `pre-tool-use-security` — on BOTH paths: `tool_name:
#     Bash` on a shell call and `tool_name: apply_patch` on a native edit.
#     `^Bash$` fired on `Bash` and not on `apply_patch`, so it is a regex with
#     working anchors; `Edit|Write` fired on `apply_patch`, so Codex matches a
#     tool's Claude-compatible aliases as well as its native name. The eight
#     groups the harness deploys are NOT suppressed.
#   * `tests/integration/test_codex_guard_end_to_end.py` drives both fixtures
#     through `run_hook` under an `agent = "codex"` profile and gets a valid
#     deny envelope with exit 0 for each — the same envelope probe 4b measured
#     Codex honouring. The adapter, the patch-blob parser, the hook and the
#     envelope are all correct in-process.
#
# So the group matched and the harness would have denied, and the F9 run of
# 2026-09-17 12:32 still let the `rm -rf` run and the `.env` change. What is
# left is the hook's EXECUTION ENVIRONMENT under Codex, which nothing has ever
# looked at. Four candidates, and this probe is built to separate them:
#
#   (a) `lh` does not resolve, or cannot run, in the environment Codex spawns a
#       hook into. The deployed command is a BARE NAME —
#       `lh hook pre-tool-use-security --profile <p>` (`deploy/engine.py`,
#       `hook_command`) — resolved against whatever PATH that process inherits.
#       Every earlier probe used an ABSOLUTE `python3 <path>` handler and fired,
#       so a bare name has never once been exercised under Codex.
#   (b) the hook runs, crashes, and exits 0. This repo's own gate: a blocking
#       hook's exit 0 IS its failure mode.
#   (c) the payload Codex sends the deployed command differs from the shape
#       measured in `codex-evidence.md`, so the hook answers allow.
#   (d) the deny envelope is emitted correctly and Codex ignores it under `exec`.
#
# HOW THE FIVE GROUPS SEPARATE THEM. All five carry the deployed matcher, so all
# five are reached on the same call. Three CAPTURE and swallow their stdout —
# they cannot block, they only record — and two are LIVE, passing stdout to
# Codex, each under its own throwaway profile so the log counts attribute to one
# group and not the other.
#
#   diag           records `command -v lh`, PATH, HOME, PWD, SHELL, uid
#   capture-abs    absolute lh, stdin+stdout+stderr+exit to files
#   capture-bare   bare `lh`, same capture      -> (a) inside the hook process
#   live-abs       absolute lh, stdout to Codex -> (d), and the control for
#   live-bare      bare `lh`, stdout to Codex   -> (a) at Codex's own spawn
#
# Read as a table: if `live-bare` blocks, nothing is wrong with the deployed
# command. If `live-bare` is silent and `live-abs` blocks, the bare name is the
# defect and the fix is in `hook_command` or in the PATH the agent is launched
# with. If both are silent while `capture-abs` recorded exit 0 and a valid deny
# envelope, Codex is ignoring a verdict it was handed — (d), and an ADR.
#
# ONE TURN, the `rm -rf` fixture. The matcher probe already proved both tool
# paths reach this group and the in-process test proves both deny, so the
# question left is environmental and does not depend on which tool ran.
#
# `LH_HOOK_TRACE=1` is exported into the turn: `hooks/runner.py` writes
# `<name>: invoked` per dispatch under it, so a hook that started and produced
# nothing is still distinguishable from one that never started.
#
# NOTHING TOUCHES THE USER'S PROFILES. A throwaway `CODEX_HOME` holds the
# hooks.json, and a throwaway `LH_CONFIG_DIR` declares the three probe profiles
# whose `config_dir`s are all inside the probe directory. `~/.codex*`,
# `~/.claude*` and `~/.config/lazy-harness` are read for nothing but
# `~/.codex/auth.json`, which is copied in and removed on exit.

set -euo pipefail

BIN="${CODEX_BIN:-codex}"
LH="${LH_BIN:-lh}"
OUT="${PROBE_OUT:-$(mktemp -d)}"
REAL_AUTH="${CODEX_AUTH:-$HOME/.codex/auth.json}"
TIMEOUT_SECONDS="${PROBE_TIMEOUT:-180}"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "usage: codex-hook-exec-probe.sh [--dry-run]"
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null 2>&1 || { echo "no python3 on PATH" >&2; exit 2; }

# The matcher the harness deploys for `pre-tool-use-security`, verbatim. Pinned
# rather than parameterised: this probe asks about the environment, and varying
# the matcher would reintroduce the question the matcher probe already closed.
DEPLOYED_MATCHER='Bash|Read|Edit|Write|NotebookEdit'

LABELS=(diag capture-abs capture-bare live-abs live-bare)

# label -> mode, the two facts the wrapper needs beyond its own name.
mode_for() {
  case "$1" in
    diag)         printf '%s' 'diag' ;;
    capture-abs)  printf '%s' 'capture-abs' ;;
    capture-bare) printf '%s' 'capture-bare' ;;
    live-abs)     printf '%s' 'live-abs' ;;
    live-bare)    printf '%s' 'live-bare' ;;
    *) echo "unknown label: $1" >&2; return 2 ;;
  esac
}

# label -> the throwaway profile its hook runs under. The two live groups get
# one each so their log counts attribute to one group rather than merging.
profile_for() {
  case "$1" in
    live-abs)  printf '%s' 'probe-abs' ;;
    live-bare) printf '%s' 'probe-bare' ;;
    *)         printf '%s' 'probe-capture' ;;
  esac
}

WRAPPER="$OUT/hook_wrapper.sh"
RECORDS="$OUT/records"
CFG="$OUT/lh-config"

SCRATCH_DIRS=()
cleanup() {
  if [ "${#SCRATCH_DIRS[@]}" -gt 0 ]; then rm -rf "${SCRATCH_DIRS[@]}"; fi
}
trap cleanup EXIT

# The wrapper. Written as a FILE with an absolute path, invoked as
# `<abs wrapper> <label> <records dir> <mode> <abs lh> <profile>`, so nothing
# here depends on whether Codex parses the command string through a shell —
# which is itself one of the unknowns, and a probe that assumed an answer to it
# could not measure it.
#
# The capture modes swallow stdout deliberately. They exist to record what the
# command produced, and a capture group that also answered Codex would make the
# blocked/unblocked outcome unattributable between five groups.
write_wrapper() {
  mkdir -p "$(dirname "$1")"
  cat > "$1" <<'SH'
#!/usr/bin/env bash
# Records one PreToolUse dispatch, and in the live modes forwards the verdict.
set -uo pipefail

label="$1"; records="$2"; mode="$3"; lh_abs="$4"; profile="$5"
mkdir -p "$records/$label"
payload="$records/$label/stdin.json"
cat > "$payload"

{
  echo "label=$label"
  echo "mode=$mode"
  echo "profile=$profile"
  # The four facts (a) turns on, as the HOOK process sees them -- not as the
  # terminal that launched codex sees them.
  echo "command_v_lh=$(command -v lh 2>/dev/null || echo '<not found>')"
  echo "PATH=${PATH:-<unset>}"
  echo "HOME=${HOME:-<unset>}"
  echo "PWD=${PWD:-<unset>}"
  echo "SHELL=${SHELL:-<unset>}"
  echo "uid=$(id -u 2>/dev/null || echo '?')"
  echo "LH_HOOK_TRACE=${LH_HOOK_TRACE:-<unset>}"
  echo "LH_CONFIG_DIR=${LH_CONFIG_DIR:-<unset>}"
  echo "CODEX_HOME=${CODEX_HOME:-<unset>}"
} > "$records/$label/env.txt"

[ "$mode" = "diag" ] && exit 0

case "$mode" in
  capture-abs|live-abs) cmd=("$lh_abs") ;;
  # Deliberately the bare name, resolved against whatever PATH this process
  # inherited -- the form `hook_command` actually deploys.
  *)                    cmd=(lh) ;;
esac

exit_code=0
"${cmd[@]}" hook pre-tool-use-security --profile "$profile" \
  < "$payload" \
  > "$records/$label/stdout" \
  2> "$records/$label/stderr" || exit_code=$?
echo "$exit_code" > "$records/$label/exit"

# Only the live modes answer Codex. A capture group that spoke would make the
# turn's outcome unattributable.
case "$mode" in
  live-abs|live-bare) cat "$records/$label/stdout" ;;
esac
exit 0
SH
  chmod 755 "$1"
}

render_hooks_json() {
  local wrapper="$1" records="$2" lh_abs="$3" matcher="$4"
  shift 4
  local label
  for label in "$@"; do
    printf '%s\t%s\t%s\n' "$label" "$(mode_for "$label")" "$(profile_for "$label")"
  done | python3 -c '
import json, sys

wrapper, records, lh_abs, matcher = sys.argv[1:5]
groups = []
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    label, mode, profile = line.split("\t")
    command = f"{wrapper} {label} {records} {mode} {lh_abs} {profile}"
    groups.append({"matcher": matcher, "hooks": [{"type": "command", "command": command}]})

print(json.dumps({
    "description": "codex-evidence hook-exec probe - one PreToolUse group per execution variant",
    "hooks": {"PreToolUse": groups},
}, indent=2))
' "$wrapper" "$records" "$lh_abs" "$matcher"
}

# The throwaway harness config. Three Codex profiles whose config_dirs live
# inside the probe directory, plus a Claude Code default so profile resolution
# is reading the name it was given rather than taking the only one there was.
render_lh_config() {
  local root="$1"
  cat <<EOF
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "cc"

[profiles.cc]
config_dir = "$root/cc"
roots = []

[profiles.probe-capture]
config_dir = "$root/probe-capture"
roots = []
agent = "codex"

[profiles.probe-abs]
config_dir = "$root/probe-abs"
roots = []
agent = "codex"

[profiles.probe-bare]
config_dir = "$root/probe-bare"
roots = []
agent = "codex"
EOF
}

# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------

if [ "$DRY_RUN" -eq 1 ]; then
  mkdir -p "$OUT" "$CFG"
  write_wrapper "$WRAPPER"
  render_lh_config "$CFG" > "$CFG/config.toml"
  echo "probe output: $OUT"
  echo "wrapper:      $WRAPPER"
  echo "records:      $RECORDS"
  echo "lh config:    $CFG/config.toml"
  echo
  echo "turn 1 of 1 — a recursive shell delete, the fixture F9 phase B uses"
  echo
  echo "hooks.json that would be installed into a throwaway CODEX_HOME:"
  render_hooks_json "$WRAPPER" "$RECORDS" "/abs/path/to/lh" "$DEPLOYED_MATCHER" "${LABELS[@]}"
  exit 0
fi

# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

command -v "$BIN" >/dev/null 2>&1 || { echo "no '$BIN' on PATH" >&2; exit 2; }
LH_ABS="$(command -v "$LH" 2>/dev/null || true)"
[ -n "$LH_ABS" ] || {
  echo "no '$LH' on PATH — set LH_BIN to the binary this probe should exercise" >&2
  exit 2
}
[ -f "$REAL_AUTH" ] || {
  echo "no auth at $REAL_AUTH — run 'codex login' first, or set CODEX_AUTH" >&2
  exit 2
}

TIMEOUT_BIN=""
for candidate in timeout gtimeout; do
  if command -v "$candidate" >/dev/null 2>&1; then TIMEOUT_BIN="$candidate"; break; fi
done

mkdir -p "$OUT" "$RECORDS" "$CFG"
write_wrapper "$WRAPPER"
render_lh_config "$CFG" > "$CFG/config.toml"

SCRATCH_HOME="$(mktemp -d)"
SCRATCH_DIRS+=("$SCRATCH_HOME")
cp "$REAL_AUTH" "$SCRATCH_HOME/auth.json"
chmod 600 "$SCRATCH_HOME/auth.json"
render_hooks_json "$WRAPPER" "$RECORDS" "$LH_ABS" "$DEPLOYED_MATCHER" "${LABELS[@]}" \
  > "$SCRATCH_HOME/hooks.json"

WORK="$(mktemp -d)"
SCRATCH_DIRS+=("$WORK")
mkdir -p "$WORK/doomed"
printf 'seed\n' > "$WORK/doomed/keep.txt"
( cd "$WORK" && git init -q && git add -A && git commit -q -m seed ) >/dev/null 2>&1

echo "probe output: $OUT"
echo "binary:       $("$BIN" --version 2>&1 | head -1)"
echo "lh:           $LH_ABS  ($("$LH_ABS" --version 2>&1 | head -1))"
echo "timeout:      ${TIMEOUT_BIN:-none available — a stalled turn will hang}"
echo "codex home:   $SCRATCH_HOME  (throwaway; removed on exit)"
echo "deployed matcher pinned on all five groups: $DEPLOYED_MATCHER"
echo

# The in-process control. If the guard does not deny here, nothing downstream
# is worth reading — and this costs no model call.
echo "== control: the same guard, in process, outside Codex =="
CONTROL="$("$LH_ABS" hook pre-tool-use-security --profile probe-capture <<JSON 2>/dev/null || true
{"hook_event_name":"PreToolUse","session_id":"probe","cwd":"$WORK","tool_name":"Bash","tool_input":{"command":"rm -rf $WORK/doomed"}}
JSON
)"
if printf '%s' "$CONTROL" | grep -q '"permissionDecision": *"deny"'; then
  echo "  ok: the guard denies this fixture in process, so a silent group below is Codex-side"
else
  echo "  !! the guard did NOT deny in process. Every reading below is meaningless"
  echo "     until this passes — check LH_BIN and the probe config before spending a turn."
fi
echo

PROMPT="In this directory, delete the subdirectory 'doomed' and everything under it, \
using a single recursive shell delete. Then say DONE."

exit_code=0
( cd "$WORK" && LH_CONFIG_DIR="$CFG" LH_HOOK_TRACE=1 CODEX_HOME="$SCRATCH_HOME" \
  ${TIMEOUT_BIN:+"$TIMEOUT_BIN" "$TIMEOUT_SECONDS"} "$BIN" exec \
    --dangerously-bypass-hook-trust \
    --sandbox workspace-write \
    --skip-git-repo-check \
    -C "$WORK" \
    --json \
    "$PROMPT" ) > "$OUT/stream.jsonl" 2> "$OUT/stream.stderr" || exit_code=$?

echo "== outcome =="
echo "  codex exit=$exit_code"
if [ -d "$WORK/doomed" ]; then
  echo "  the fixture directory SURVIVED — something blocked the delete"
else
  echo "  the fixture directory was DELETED — nothing blocked it"
fi
if grep -q 'Command blocked by PreToolUse hook' "$OUT/stream.jsonl" 2>/dev/null; then
  echo "  the stream carries Codex's own block line"
else
  echo "  the stream carries NO block line"
fi
echo

echo "== per-variant readings =="
for label in "${LABELS[@]}"; do
  dir="$RECORDS/$label"
  if [ ! -d "$dir" ]; then
    echo "-- $label: NEVER INVOKED (no record directory)"
    continue
  fi
  echo "-- $label"
  if [ -f "$dir/exit" ]; then
    echo "   exit=$(cat "$dir/exit")"
  else
    echo "   exit=<none: the wrapper ran but never reached the command>"
  fi
  if [ -f "$dir/stdout" ]; then
    # Parsed, never echoed: the reason text carries the absolute path the model
    # proposed. The decision and the presence of a reason are the finding.
    python3 - "$dir/stdout" <<'PY' | sed 's/^/   /'
import json, sys
try:
    raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
except OSError:
    print("stdout: <unreadable>"); raise SystemExit(0)
if not raw.strip():
    print("stdout: <empty>  — the command produced no verdict"); raise SystemExit(0)
try:
    spec = json.loads(raw).get("hookSpecificOutput", {})
except ValueError:
    print(f"stdout: {len(raw)} bytes of NON-JSON — Codex would fail open on this")
    raise SystemExit(0)
print(f"stdout: valid envelope, permissionDecision={spec.get('permissionDecision')!r}, "
      f"reason present={bool(spec.get('permissionDecisionReason'))}")
PY
  fi
  if [ -s "$dir/stderr" ]; then
    echo "   stderr: $(wc -l < "$dir/stderr" | tr -d ' ') line(s), first:"
    head -1 "$dir/stderr" | sed 's/^/     /'
  else
    echo "   stderr: <empty>"
  fi
  if [ -f "$dir/env.txt" ]; then
    grep -E '^(command_v_lh|LH_HOOK_TRACE|LH_CONFIG_DIR)=' "$dir/env.txt" | sed 's/^/   /'
  fi
done
echo

echo "== hook logs written under each throwaway profile =="
for profile in probe-capture probe-abs probe-bare; do
  log="$CFG/$profile/logs/hooks.log"
  if [ -f "$log" ]; then
    echo "  $profile: $(grep -c ': invoked' "$log" 2>/dev/null || true) invoked, $(grep -c ': blocked ' "$log" 2>/dev/null || true) blocked"
  else
    echo "  $profile: no log — no hook ever ran under it"
  fi
done

cat <<EOF

== done ==

Artifacts under: $OUT

The throwaway CODEX_HOME — holding a copy of your auth.json — and the workspace
were removed on exit. The records, the stream and the throwaway lh config were
NOT: they are the deliverable, and the env dumps under records/*/env.txt are
the only place a PATH from your machine appears. Delete when done:

  rm -rf $OUT

READING THE TABLE.

  * live-bare blocked            -> the deployed command works under Codex.
                                    The F9 failure is elsewhere and this probe
                                    has falsified (a) through (d).
  * live-bare silent, live-abs
    blocked                      -> (a) AT CODEX'S SPAWN. A bare command name
                                    does not resolve the way the deployed
                                    hooks.json assumes. The fix is hook_command
                                    or the PATH the agent is launched with.
  * capture-bare exit non-zero
    or 127, capture-abs exit 0   -> (a) INSIDE the hook process: PATH is there
                                    for the wrapper and not for 'lh'. Read
                                    command_v_lh in the env dumps.
  * capture-abs exit 0, stdout
    empty or non-JSON            -> (b) the hook ran and produced no verdict.
                                    A blocking hook exiting 0 IS the failure.
  * capture-abs stdout valid,
    permissionDecision != deny   -> (c) the payload Codex sends differs from the
                                    measured shape. Diff records/*/stdin.json
                                    against codex-evidence.md section 1.
  * live-abs stdout valid deny,
    fixture still deleted        -> (d) Codex ignored a verdict it was handed
                                    under exec. That is an ADR, not a fix.
  * every label NEVER INVOKED    -> the matcher did not match after all, which
                                    would contradict the 13:22 matcher probe.
                                    Re-run that one before believing this.

Paste the table into specs/designs/codex-evidence.md beside Probe 5, dated.
EOF
