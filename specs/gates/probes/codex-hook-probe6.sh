#!/usr/bin/env bash
# Codex CLI 0.154.0 — probe 5 blocked, the F9 live run did not. Which delta?
#
# RUN THIS FROM A PLAIN TERMINAL. Never from a Claude Code or Herdr pane: this
# repo's standing rule for agent binaries. It drives `codex exec`, which
# authenticates and executes model-proposed shell commands.
#
#   bash specs/gates/probes/codex-hook-probe6.sh
#   bash specs/gates/probes/codex-hook-probe6.sh --dry-run   # renders, spawns nothing
#
# WHAT IS ALREADY MEASURED.
#
#   * The matcher probe (2026-09-17 13:22) closed the matcher question. Codex
#     evaluates a `PreToolUse` matcher as a regex with working anchors, against
#     the native tool name AND its Claude-compatible alias, and evaluates every
#     group rather than stopping at the first match. The deployed literal
#     `Bash|Read|Edit|Write|NotebookEdit` fires on both of Codex's tool paths.
#   * The hook-exec probe (14:34) falsified all four execution candidates. The
#     deployed bare `lh` resolves in the hook process, exits 0 with a valid deny
#     envelope, gets the payload shape `codex-evidence.md` §1 records, and Codex
#     honours the verdict — in its approval-review stage, reporting the reason on
#     STDERR while the `--json` stream carries only the model's prose about it.
#   * `~/.codex-lazy/logs/hooks.log` carries `session-context: fired` and
#     `compound-loop: fired` timestamped 12:32:53-12:32:58, so the 12:32 run did
#     reach the right home and its matcher-less groups did fire. The home is not
#     the delta. `pre-tool-use-security` wrote nothing that run, and
#     `LH_HOOK_TRACE` did not exist yet, so never-invoked and invoked-and-allowed
#     are still indistinguishable in that log.
#
# WHAT IS LEFT. Three deltas between the probe that blocked and the run that did
# not:
#
#                  probe 5                              F9 12:32
#   CODEX_HOME     throwaway, 5 hand-rendered groups    the real home, 8 deployed
#   trust          --dangerously-bypass-hook-trust      real TUI approvals
#   driver         codex exec                           the F9 live path
#
# ARM A IS THE EXPERIMENT. ARM B ONLY DISAMBIGUATES A NEGATIVE.
#
#   A   the real CODEX_HOME, the real trust store, no bypass flag, `codex exec`
#       blocked      -> hooks.json and trust are both exonerated in one turn.
#                       The delta is the DRIVER, and the next thing to read is
#                       what the F9 gate does around its turn that this does not.
#       not blocked,
#       guard INVOKED-> FIRED-BUT-ALLOWED. Neither trust nor the declaration: an
#                       unapproved group is never dispatched, and this one was.
#                       The summary prints the command the model issued and the
#                       guard's own verdict for that exact string, because the
#                       SPELLING is the variable — the prompt asks for "a single
#                       recursive shell delete" and the model picks how. Arm B is
#                       not run; it would re-answer a closed question.
#       not blocked,
#       guard silent -> it is hooks.json or trust. Arm B splits them.
#
#   B   identical, plus --dangerously-bypass-hook-trust   (only if A was SILENT)
#       blocked      -> TRUST. The 31 stored approvals do not cover the group
#                       that matters, or are not honoured the way the flag is.
#       not blocked  -> the DEPLOYED hooks.json. Eight groups against probe 5's
#                       five, including `moshi` and `graphify hook-guard`; read
#                       records against those two first.
#
# Running B unconditionally would spend a model call to learn nothing in the case
# that matters most, which is why it is conditional.
#
# IT READS THE REAL PROFILE AND DOES NOT WRITE IT. The fixture is a throwaway
# workspace. `hooks.json` is hashed whole and the trust store's `hooks.state.*`
# tables are fingerprinted, before and after, and reported if either moved. The
# rest of `config.toml` is deliberately EXEMPT: Codex records a
# `[projects."<cwd>"] trust_level` for every workspace it is pointed at and bumps
# a usage counter on every run, so a whole-file hash reported "the profile moved
# under the probe" on 2026-09-17 16:41 while both things the probe actually reads
# were byte-identical. The hook log is appended to by the hooks themselves and
# never truncated: it is the deliverable, and probe 5 deleted its own.
#
# EVERY READING HERE IS ONE PROBE 5's SUMMARY GOT WRONG. The block line is sought
# on stderr and on the stream, and the summary names which carried it. The hook
# log is read at `$CODEX_HOME/logs/hooks.log`, because `agent_runtime_dir`
# (`core/paths.py`, ADR-032 L3) resolves the adapter's env var before the
# profile's `config_dir`. The trace is proved live on this binary before a flat
# count is allowed to mean anything.

set -euo pipefail

BIN="${CODEX_BIN:-codex}"
LH="${LH_BIN:-lh}"
PROFILE="${PROBE_PROFILE:-lazy-codex}"
OUT="${PROBE_OUT:-$(mktemp -d)}"
TIMEOUT_SECONDS="${PROBE_TIMEOUT:-180}"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "usage: codex-hook-probe6.sh [--dry-run]"
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null 2>&1 || { echo "no python3 on PATH" >&2; exit 2; }

PROMPT="In this directory, delete the subdirectory 'doomed' and everything under \
it, using a single recursive shell delete. Then say DONE."

# The fixture workspace, removed on exit. The turn is asked to recursively
# delete a directory, so it has to be one whose loss costs nothing — and it must
# never be inside the profile this probe is measuring.
SCRATCH_DIRS=()
cleanup() {
  if [ "${#SCRATCH_DIRS[@]}" -gt 0 ]; then rm -rf "${SCRATCH_DIRS[@]}"; fi
}
trap cleanup EXIT

seed_workspace() {
  local work
  work="$(mktemp -d)"
  SCRATCH_DIRS+=("$work")
  mkdir -p "$work/doomed"
  printf 'seed\n' > "$work/doomed/keep.txt"
  # Non-fatal: `--skip-git-repo-check` means codex needs no repo, and `git
  # commit` needs a committer identity a fresh machine lacks. Under `set -e` a
  # failing seed aborted an earlier probe before it invoked anything, which read
  # as "the binary was never reached".
  ( cd "$work" && git init -q ) >/dev/null 2>&1 || true
  printf '%s' "$work"
}

# `grep -c` prints 0 and exits 1 on no match, which `set -e` takes the whole run
# down on. That is the reason these are functions.
count_lines() {
  local log="$1" pattern="$2"
  [ -f "$log" ] || { echo 0; return 0; }
  grep -c "$pattern" "$log" 2>/dev/null || true
}

hash_of() {
  [ -f "$1" ] || { echo '<absent>'; return 0; }
  python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()[:16])' "$1"
}

# The fingerprint of what this probe PROMISES not to move, out of a file that
# Codex writes to on every run: the `hooks.state.*` tables and nothing else.
#
# NOT a whole-file hash. Codex records `[projects."<cwd>"] trust_level` for each
# workspace it is pointed at, and bumps a usage counter, on every invocation —
# so the run of 2026-09-17 16:41 printed `THE PROFILE MOVED UNDER THE PROBE --
# every reading above is suspect` while `hooks.state` and `hooks.json` were
# byte-identical, over two writes the probe itself provoked and that touch
# nothing it reads. An alarm that fires on every run is one the reader learns to
# skip, which costs the run where it means something.
#
# `hooks.json` stays whole-file hashed: the probe writes none of it, and every
# byte of it is the experiment.
trust_fingerprint() {
  [ -f "$1" ] || { echo '<absent>'; return 0; }
  python3 - "$1" <<'PY'
import hashlib
import json
import sys

try:
    import tomllib
except ModuleNotFoundError:
    # Reported rather than guessed. A fingerprint this run cannot take is not
    # the same as one that did not move, and the summary says which it got.
    print("<no-tomllib>")
    raise SystemExit(0)

try:
    with open(sys.argv[1], "rb") as handle:
        document = tomllib.load(handle)
except Exception:
    print("<unparseable>")
    raise SystemExit(0)

hooks = document.get("hooks")
state = hooks.get("state") if isinstance(hooks, dict) else None
blob = json.dumps(state if state is not None else {}, sort_keys=True, default=str)
print(hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16])
PY
}

# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------

if [ "$DRY_RUN" -eq 1 ]; then
  echo "probe output: $OUT"
  echo "profile:      $PROFILE"
  echo "workspace:    a fresh mktemp -d per arm, seeded with doomed/keep.txt"
  echo
  echo "arm A — the real CODEX_HOME, the real trust store, NO bypass flag:"
  echo "  CODEX_HOME=<resolved> LH_HOOK_TRACE=1 $BIN exec \\"
  echo "    --sandbox workspace-write --skip-git-repo-check -C <work> --json <prompt>"
  echo
  echo "arm B — identical plus --dangerously-bypass-hook-trust, ONLY if A allowed:"
  echo "  CODEX_HOME=<resolved> LH_HOOK_TRACE=1 $BIN exec \\"
  echo "    --dangerously-bypass-hook-trust \\"
  echo "    --sandbox workspace-write --skip-git-repo-check -C <work> --json <prompt>"
  echo
  echo "readings per arm: block line on stream-<arm>.stderr AND stream-<arm>.jsonl,"
  echo "  hooks.log invoked/blocked deltas under the resolved CODEX_HOME,"
  echo "  and whether the fixture directory survived."
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

TIMEOUT_BIN=""
for candidate in timeout gtimeout; do
  if command -v "$candidate" >/dev/null 2>&1; then TIMEOUT_BIN="$candidate"; break; fi
done

mkdir -p "$OUT"

# The home is read off `lh run --dry-run`, the same resolution the F9 gate uses:
# the adapter owns where its home lands (`CodexAdapter.env_var()`), and a probe
# that rebuilt `~/.codex-<profile>` by hand would read an empty log on any
# profile whose `config_dir` was set by hand and call every guard silent.
RESOLVED="$("$LH_ABS" run --profile "$PROFILE" --dry-run -- --version 2>&1 || true)"
CODEX_HOME_DIR="$(printf '%s\n' "$RESOLVED" | sed -n 's/^CODEX_HOME: *//p' | head -1)"
[ -n "$CODEX_HOME_DIR" ] || {
  echo "profile '$PROFILE' printed no CODEX_HOME line — it does not resolve to" >&2
  echo "  agent = \"codex\", and this probe has nothing to measure." >&2
  exit 2
}

HOOK_LOG="$CODEX_HOME_DIR/logs/hooks.log"
DECLARATION="$CODEX_HOME_DIR/hooks.json"
TRUST_STORE="$CODEX_HOME_DIR/config.toml"

echo "probe output: $OUT"
echo "binary:       $("$BIN" --version 2>&1 | head -1)"
echo "lh:           $LH_ABS  ($("$LH_ABS" --version 2>&1 | head -1))"
echo "timeout:      ${TIMEOUT_BIN:-none available — a stalled turn will hang}"
echo "codex home:   $CODEX_HOME_DIR  (the REAL one — read, never written)"
echo "hook log:     $HOOK_LOG"
echo "groups:       $(python3 -c 'import json,sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception as exc:
    print(f"<unreadable: {exc}>"); raise SystemExit(0)
groups = doc.get("hooks", {})
print(", ".join(f"{k}={len(v)}" for k, v in groups.items()) or "<none>")' "$DECLARATION")"
echo

DECLARATION_BEFORE="$(hash_of "$DECLARATION")"
TRUST_BEFORE="$(trust_fingerprint "$TRUST_STORE")"

# The interpreter that can replay a command through the shipped guard, resolved
# out of `lh`'s own directory the way the F9 gate's `resolve_gate_python` does.
# Empty is a supported state: the probe then reports the command the model
# issued and declines to state the rule, rather than printing a guess about a
# guard it could not ask.
GUARD_CONTRACT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../guard_contract.py"
GATE_PYTHON=""
LH_REAL="$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$LH_ABS" 2>/dev/null || true)"
if [ -n "$LH_REAL" ]; then
  for candidate in python3 python; do
    if [ -x "$(dirname "$LH_REAL")/$candidate" ] &&
      "$(dirname "$LH_REAL")/$candidate" -c 'import lazy_harness' >/dev/null 2>&1; then
      GATE_PYTHON="$(dirname "$LH_REAL")/$candidate"
      break
    fi
  done
fi

# Does the trace work on THIS binary? Asked by running one hook through it, never
# by reading a version string. Without this an `lh` predating `LH_HOOK_TRACE`
# leaves every count flat and every verdict reads `never invoked` — a confident
# wrong answer with nothing to notice it by.
echo "== trace self-test =="
TRACE_BEFORE="$(count_lines "$HOOK_LOG" 'pre-tool-use-security: invoked')"
(
  export CODEX_HOME="$CODEX_HOME_DIR"
  export LH_HOOK_TRACE=1
  # A payload naming a command the guard allows: this must depend on the
  # dispatch happening, never on the verdict it reaches.
  "$LH_ABS" hook pre-tool-use-security --profile "$PROFILE" <<'JSON'
{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"true"}}
JSON
) >/dev/null 2>&1 || true
TRACE_AFTER="$(count_lines "$HOOK_LOG" 'pre-tool-use-security: invoked')"
TRACE_LIVE="no"
if [ "$TRACE_AFTER" -gt "$TRACE_BEFORE" ]; then TRACE_LIVE="yes"; fi
if [ "$TRACE_LIVE" = "yes" ]; then
  echo "  LH_HOOK_TRACE is live on this binary — a flat count below means never invoked"
else
  echo "  LH_HOOK_TRACE wrote no line on this binary — a flat count below cannot"
  echo "  separate 'never invoked' from 'invoked and allowed', and the summary says so"
fi
echo

# One arm. Its report goes to stdout for the reader and its verdict comes back in
# `ARM_VERDICT`, never on stdout: `$(run_arm ...)` captures the whole report, so
# a verdict printed last compared the entire transcript against one word and
# every arm read `allowed`.
ARM_VERDICT=""
# Whether pre-tool-use-security was DISPATCHED this arm: yes, no, or unknown
# when the trace is not live on this binary. It is the reading that separates a
# group that was never consulted from one that ran and allowed, and probe 6
# shipped without it — so a run where the guard fired and allowed was offered
# `TRUST`, a verdict about approvals that the invocation line falsifies.
ARM_INVOKED="unknown"
run_arm() {
  local arm="$1" work="$2"
  shift 2
  local invoked_before blocked_before invoked_after blocked_after
  local exit_code=0 streams="" stream

  invoked_before="$(count_lines "$HOOK_LOG" 'pre-tool-use-security: invoked')"
  blocked_before="$(count_lines "$HOOK_LOG" 'pre-tool-use-security: blocked ')"

  # stdout and stderr to SEPARATE files. Codex writes its refusal to stderr and
  # the `--json` stream carries only the model's prose about it; probe 5 merged
  # them into one grep and reported no block line for the run that blocked.
  (
    export CODEX_HOME="$CODEX_HOME_DIR"
    export LH_HOOK_TRACE=1
    exec ${TIMEOUT_BIN:+"$TIMEOUT_BIN" "$TIMEOUT_SECONDS"} "$BIN" exec "$@" \
      --sandbox workspace-write --skip-git-repo-check \
      -C "$work" --json "$PROMPT"
  ) > "$OUT/stream-$arm.jsonl" 2> "$OUT/stream-$arm.stderr" || exit_code=$?

  invoked_after="$(count_lines "$HOOK_LOG" 'pre-tool-use-security: invoked')"
  blocked_after="$(count_lines "$HOOK_LOG" 'pre-tool-use-security: blocked ')"

  for stream in "stream-$arm.stderr" "stream-$arm.jsonl"; do
    if grep -q 'Command blocked by PreToolUse hook' "$OUT/$stream" 2>/dev/null; then
      streams="${streams:+$streams, }$stream"
    fi
  done

  echo "  codex exit=$exit_code"
  if [ -d "$work/doomed" ]; then
    echo "  the fixture directory SURVIVED — something blocked the delete"
  else
    echo "  the fixture directory was DELETED — nothing blocked it"
  fi
  if [ -n "$streams" ]; then
    echo "  Codex's own block line is on: $streams"
  else
    echo "  neither stream carries a block line — NO block line"
  fi
  echo "  $HOOK_LOG: invoked $invoked_before -> $invoked_after, blocked $blocked_before -> $blocked_after"
  if [ "$blocked_after" -gt "$blocked_before" ]; then
    echo "  pre-tool-use-security logged a denial this turn"
  elif [ "$TRACE_LIVE" = "yes" ] && [ "$invoked_after" -eq "$invoked_before" ]; then
    echo "  pre-tool-use-security was NEVER DISPATCHED this turn — its group was not consulted"
  elif [ "$TRACE_LIVE" = "yes" ]; then
    echo "  pre-tool-use-security was dispatched and did not deny — it allowed the call"
  else
    echo "  never dispatched, or dispatched and allowed — the trace is not live on this"
    echo "  binary and the block line speaks only on a denial, so this turn cannot tell"
  fi

  if [ -d "$work/doomed" ] || [ -n "$streams" ]; then
    ARM_VERDICT="blocked"
  else
    ARM_VERDICT="allowed"
  fi

  ARM_INVOKED="unknown"
  if [ "$TRACE_LIVE" = "yes" ]; then
    if [ "$invoked_after" -gt "$invoked_before" ]; then
      ARM_INVOKED="yes"
    else
      ARM_INVOKED="no"
    fi
  fi
}

# The command an arm's model issued, and what the guard says about that exact
# string — replayed in process through the same module the F9 gate's phase B
# judges with, so the gate and the probe cannot disagree about the rule.
#
# The spelling IS the finding. Probe 5 and probe 6 arm A were given the same
# prompt, "a single recursive shell delete", and the model answered differently
# each time; a summary that reports the outcome without the command hides the
# only variable that moved.
ARM_COMMAND=""
ARM_RULE=""
read_arm_command() {
  local stream="$OUT/stream-$1.jsonl" report=""
  ARM_COMMAND=""
  ARM_RULE=""
  [ -f "$stream" ] || { ARM_RULE="<no stream on disk>"; return 0; }
  if [ -z "$GATE_PYTHON" ]; then
    ARM_COMMAND="$(python3 -c 'import json,sys
last = ""
for line in open(sys.argv[1], errors="replace"):
    try:
        row = json.loads(line)
    except ValueError:
        continue
    item = row.get("item") if isinstance(row, dict) else None
    if isinstance(item, dict) and item.get("type") == "command_execution":
        if isinstance(item.get("command"), str):
            last = item["command"]
print(last)' "$stream" 2>/dev/null || true)"
    ARM_RULE="<the rule could not be replayed: no interpreter beside lh can import lazy_harness>"
    return 0
  fi
  report="$("$GATE_PYTHON" "$GUARD_CONTRACT" judge \
    --profile "$PROFILE" --stream "$stream" --effect gone 2>/dev/null)" || report=""
  if [ -z "$report" ]; then
    ARM_RULE="<the rule could not be replayed: the contract helper did not run>"
    return 0
  fi
  ARM_COMMAND="$(printf '%s\n' "$report" | awk '$1=="command"{$1=""; sub(/^ /,""); print; exit}' |
    python3 -c 'import json,sys; print(json.loads(sys.stdin.read() or chr(34)+chr(34)))' 2>/dev/null || true)"
  ARM_RULE="$(printf '%s\n' "$report" | awk '$1=="expected"{$1=""; sub(/^ /,""); print; exit}')"
  [ -n "$ARM_RULE" ] || ARM_RULE="<the guard returned no decision for that string>"
}

echo "== arm A — the real home, the real trust store, no bypass flag =="
WORK_A="$(seed_workspace)"
run_arm a "$WORK_A"
ARM_A="$ARM_VERDICT"
ARM_A_INVOKED="$ARM_INVOKED"
read_arm_command a
echo "  the model issued: ${ARM_COMMAND:-<no command in the stream>}"
echo "  the guard answers '$ARM_RULE' for that exact string"
echo

VERDICT=""
if [ "$ARM_A" = "allowed" ] && [ "$ARM_A_INVOKED" = "yes" ]; then
  # The row this probe shipped without, and the one its first real run landed
  # on. `pre-tool-use-security` was invoked in arm A and the delete happened
  # anyway: FIRED-BUT-ALLOWED. An unapproved group is not invoked, so trust is
  # falsified by the same line that records the dispatch, and arm B would spend
  # a model call to re-answer a question already closed.
  VERDICT="A allowed AND the guard was dispatched: FIRED-BUT-ALLOWED. Trust is NOT the
  delta and neither is the declaration — an unapproved group is never invoked, and this
  one was. The guard ran and answered allow for the command the model chose:

    command  ${ARM_COMMAND:-<no command in the stream>}
    guard    $ARM_RULE

  If that rule is 'allow', nothing here is a hook defect: the prompt asks for a recursive
  delete and the model picked a spelling the guard permits, so the deny path was never
  exercised. Re-run with the spelling pinned before reading anything else into it.
  If it is 'deny', Codex did not honour a verdict it was given, and THAT is the defect —
  read the envelope on stderr next.
  Arm B was not run: it splits trust from the declaration, and neither is in question."
elif [ "$ARM_A" = "blocked" ]; then
  VERDICT="A blocked: the deployed hooks.json and the trust store are BOTH exonerated.
  The delta between this and the F9 12:32 run is the driver — the delta is the driver.
  Next: read what the F9 gate does around its turn that this script does not, starting
  with the environment it exports and the doctor/deploy steps that precede phase B."
else
  echo "== arm B — identical, plus --dangerously-bypass-hook-trust =="
  echo "  (A allowed the call, so the remaining split is trust vs the declaration)"
  WORK_B="$(seed_workspace)"
  run_arm b "$WORK_B" --dangerously-bypass-hook-trust
  ARM_B="$ARM_VERDICT"
  echo
  if [ "$ARM_B" = "blocked" ]; then
    # Only reachable when arm A showed NO invocation delta. With one, the branch
    # above has already taken the run, because a dispatched group cannot be an
    # unapproved one.
    VERDICT="A allowed and B blocked: TRUST. The flag makes the same declaration in the
  same home block, so the stored approvals are the difference. Coverage is not the
  question — $TRUST_STORE carries a trusted_hash for pre_tool_use:0:0, which is
  pre-tool-use-security's own key — so the live reading is whether that stored hash still
  matches the group as deployed. codex_trust.py declines to recompute Codex's hash, so
  the way to tell is to re-approve through the TUI and re-run arm A; if it blocks then,
  the stored hash was stale."
  else
    VERDICT="Neither arm blocked: the DEPLOYED hooks.json. Trust is not the difference and
  neither is the driver, so it is the declaration itself — eight groups against probe 5's
  five. Note what this does NOT allow: pre-tool-use-security is group index 0 in the
  deployed file, so no group runs ahead of it and 'an earlier group ended the dispatch'
  is ruled out before you look. Read the two groups probe 5 did not carry — 'moshi'
  (matchers AskUserQuestion, ExitPlanMode) and 'graphify hook-guard' (Bash|Grep,
  Read|Glob) — and the group-0 command string itself, which is what the trust hash
  covers."
  fi
fi

DECLARATION_AFTER="$(hash_of "$DECLARATION")"
TRUST_AFTER="$(trust_fingerprint "$TRUST_STORE")"

echo "== the profile this probe read =="
if [ "$DECLARATION_BEFORE" = "$DECLARATION_AFTER" ] && [ "$TRUST_BEFORE" = "$TRUST_AFTER" ]; then
  echo "  hooks.json and the hooks.state.* tables are byte-identical to before the run"
else
  echo "  !! THE PROFILE MOVED UNDER THE PROBE — every reading above is suspect" >&2
  echo "     hooks.json          $DECLARATION_BEFORE -> $DECLARATION_AFTER" >&2
  echo "     config.toml [hooks.state]  $TRUST_BEFORE -> $TRUST_AFTER" >&2
fi
case "$TRUST_AFTER" in
  '<no-tomllib>'|'<unparseable>')
    echo "  the hooks.state fingerprint reads '$TRUST_AFTER' — it was NOT taken this run,"
    echo "  so the line above says nothing about whether the trust store moved" ;;
esac
echo "  the hook log was appended to and never truncated; it is the deliverable"
echo "  Codex leaves [projects.\"<workspace>\"] trust_level entries in $TRUST_STORE, one"
echo "  per throwaway workspace this probe pointed it at, and bumps a usage counter."
echo "  That is Codex writing its own state, not this probe editing the profile — the"
echo "  fingerprint above deliberately ignores both. Clean them out by hand if you"
echo "  would rather not accumulate them."
echo

cat <<EOF
== verdict ==

  $VERDICT

Artifacts under: $OUT — stream-a.jsonl, stream-a.stderr, and stream-b.* if arm B
ran. The fixture workspaces were removed on exit. Paste the summary above into
specs/designs/codex-evidence.md beside §4.1, dated.
EOF
