#!/usr/bin/env bash
# Codex CLI 0.154.0 — the probe that decides ADR-049's per-level bypass mapping.
#
# RUN THIS FROM A PLAIN TERMINAL. Never from a Claude Code or Herdr pane: this
# repo's standing rule for agent binaries, and the one that blocked the first
# round of Codex probes on 2026-09-16 before they ran. It drives `codex exec`,
# which authenticates and executes model-proposed shell commands.
#
#   bash specs/gates/probes/codex-bypass-probe.sh
#
# WHY IT EXISTS. `lh run --bypass=enable|activate|no-sandbox` asks each adapter
# for the flags of one declared position, and an adapter that has no such
# position must say `None` rather than forward a neighbouring flag. For Claude
# Code the mapping is legible from its own flag names. For Codex it is not:
# 0.154.0 offers an approval policy, a sandbox policy and a single combined
# `--dangerously-bypass-approvals-and-sandbox`, with no flag that means
# "available but off". Which of those is ENABLE, and whether ACTIVATE and
# NO_SANDBOX are two positions or one, is a behavioural question.
#
# WHAT `--help` ALREADY SETTLED, AND WHAT IT CANNOT. Read from `codex --help`
# and `codex exec --help` on 0.154.0 — evidence level [help], which proves a
# flag exists and never what it does:
#
#   * `--full-auto` DOES NOT EXIST on this version, at either level. Any design
#     text naming it is describing an older CLI.
#   * `-a, --ask-for-approval <on-request|never>` is on the TOP-LEVEL command
#     ONLY. `codex exec` has no such option. Phase 0 below re-asks that as a
#     run, because an option absent from help text and an option undocumented
#     but accepted are different findings and only one of them is a blocker.
#   * `-s, --sandbox <read-only|workspace-write|danger-full-access>` and
#     `--dangerously-bypass-approvals-and-sandbox` are on both.
#   * `-c approval_policy="never"` reaches the same setting through the config
#     override, which IS on `codex exec`.
#
# THE TWO TARGETS ARE THE POINT. Each level asks the model to write a marker to
# two places outside the workspace: one under `$HOME` and one under a temp
# directory. A single target would misread the macOS Seatbelt policy, which has
# shipped permitting temp-directory writes under `workspace-write` — a level
# scored on the temp target alone would read as "bypassed" when it merely wrote
# somewhere the sandbox already allowed. `$HOME` is the strict target; the temp
# one is the control that tells you which of the two you are looking at.
#
# BASELINE IS A CONTROL, NOT A ROW. If the no-flags run writes the `$HOME`
# target, there was no sandbox to bypass on this machine and every other row is
# meaningless. The summary says so rather than leaving you to notice.
#
# AUTH IS COPIED, and that is the repo's measured convention rather than a
# shortcut: `~/.codex/auth.json` lives inside `CODEX_HOME`, so a disposable home
# has no credential at all (`specs/designs/codex-evidence.md:89-90` — all six
# earlier probes copy it). The copy never leaves this machine and the throwaway
# home is what keeps the user's real hooks, config and trust state out of the
# measurement.
#
# THE SUMMARY PRINTS KINDS AND TYPES, NEVER BODIES. `codex_bypass_summary.py`
# beside this file does that half, and `tests/unit/test_codex_bypass_summary.py`
# asserts it: a stream carries the prompt, the proposed command and the
# workspace path, and this output is meant to be pasted into a public repo.

set -euo pipefail

BIN="${CODEX_BIN:-codex}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMARY="$HERE/codex_bypass_summary.py"
OUT="${PROBE_OUT:-$(mktemp -d)}"
MARKER="codex-bypass-probe-$$"
REAL_AUTH="${CODEX_AUTH:-$HOME/.codex/auth.json}"
# A run that stalls on an approval it cannot receive would otherwise hang the
# whole probe. `timeout` is GNU; macOS ships it only via coreutils as `gtimeout`.
TIMEOUT_SECONDS="${PROBE_TIMEOUT:-180}"

command -v "$BIN" >/dev/null 2>&1 || { echo "no '$BIN' on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "no python3 on PATH" >&2; exit 2; }
[ -f "$SUMMARY" ] || { echo "missing summary printer: $SUMMARY" >&2; exit 2; }
[ -f "$REAL_AUTH" ] || {
  echo "no auth at $REAL_AUTH — run 'codex login' first, or set CODEX_AUTH" >&2
  exit 2
}

TIMEOUT_BIN=""
for candidate in timeout gtimeout; do
  if command -v "$candidate" >/dev/null 2>&1; then TIMEOUT_BIN="$candidate"; break; fi
done

# Every `$HOME` marker this run creates, removed on the way out however it ends.
# A probe that litters the user's home directory is a probe run once.
HOME_TARGETS=()
cleanup() {
  if [ "${#HOME_TARGETS[@]}" -gt 0 ]; then rm -f "${HOME_TARGETS[@]}"; fi
}
trap cleanup EXIT

echo "probe output: $OUT"
echo "binary:       $("$BIN" --version 2>&1 | head -1)"
echo "timeout:      ${TIMEOUT_BIN:-none available — a stalled run will hang}"
echo

# The candidate flag sets, in the order the reading depends on: the control
# first, then the one help text says should not parse, then the positions.
CANDIDATES=(
  baseline
  approval-never-flag
  approval-never-config
  approve-for-me
  sandbox-danger
  never-plus-danger
  bypass-all
)

# Sets the global `FLAGS`. A function rather than a parallel array because the
# `-c key="value"` entries carry spaces and quotes that word-splitting eats.
set_flags() {
  case "$1" in
    baseline)              FLAGS=() ;;
    approval-never-flag)   FLAGS=(-a never) ;;
    approval-never-config) FLAGS=(-c 'approval_policy="never"') ;;
    approve-for-me)        FLAGS=(--approve-for-me) ;;
    sandbox-danger)        FLAGS=(-s danger-full-access) ;;
    never-plus-danger)     FLAGS=(-c 'approval_policy="never"' -s danger-full-access) ;;
    bypass-all)            FLAGS=(--dangerously-bypass-approvals-and-sandbox) ;;
    *) echo "unknown candidate: $1" >&2; return 2 ;;
  esac
}

# `"${FLAGS[@]}"` on an empty array is an unbound-variable error under `set -u`
# in bash 3.2, which is what `/bin/bash` still is on macOS. The `+` form expands
# to nothing at all when the array is empty, which is what `baseline` needs.
expand_flags() {
  printf '%s\n' ${FLAGS[@]+"${FLAGS[@]}"}
}

run_with_timeout() {
  if [ -n "$TIMEOUT_BIN" ]; then
    "$TIMEOUT_BIN" "$TIMEOUT_SECONDS" "$@"
  else
    "$@"
  fi
}

# ---------------------------------------------------------------------------
# Phase 0 — does `codex exec` accept the flags at all
# ---------------------------------------------------------------------------
# Appending `--help` makes clap parse the options and then short-circuit: exit 0
# means the option exists on this subcommand, a non-zero exit with an
# `unexpected argument` on stderr means it does not. No model call, no auth, no
# execution — so this phase is free and it runs before anything that costs.
#
# It exists because `-a/--ask-for-approval` is documented at the top level and
# absent from `codex exec --help`, and "absent from help" is not the same claim
# as "rejected by the parser".

echo "== phase 0: argv acceptance on 'codex exec' =="
PARSES=()
for name in "${CANDIDATES[@]}"; do
  set_flags "$name"
  if run_with_timeout "$BIN" exec ${FLAGS[@]+"${FLAGS[@]}"} --help \
      >"$OUT/parse-$name.stdout" 2>"$OUT/parse-$name.stderr"; then
    PARSES+=("$name")
    echo "  $name: accepted   [$(expand_flags | tr '\n' ' ')]"
  else
    echo "  $name: REFUSED    [$(expand_flags | tr '\n' ' ')]"
    head -3 "$OUT/parse-$name.stderr" | sed 's/^/      /'
  fi
done
echo
echo "  (a REFUSED row is a finding for ADR-049, not a bug in this probe: it"
echo "   means that spelling cannot be what bypass_argv returns for codex.)"
echo

if [ "${#PARSES[@]}" -eq 0 ]; then
  echo "NOTHING PARSED. Stop here — phase 1 would measure the parser, not bypass." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Phase 1 — what each accepted level actually permits
# ---------------------------------------------------------------------------

echo "== phase 1: observed behaviour per level =="
echo

for name in "${PARSES[@]}"; do
  set_flags "$name"

  home="$(mktemp -d)"
  cp "$REAL_AUTH" "$home/auth.json"
  work="$(mktemp -d)"
  printf 'workspace fixture\n' > "$work/fixture.txt"

  # The strict target: outside the workspace and outside any temp directory a
  # sandbox policy might already permit.
  home_target="$HOME/.lazy-harness-$MARKER-$name.txt"
  HOME_TARGETS+=("$home_target")
  rm -f "$home_target"
  # The control target: also outside the workspace, but somewhere Seatbelt has
  # shipped allowing under `workspace-write`.
  tmp_target="$(mktemp -d)/outside-$name.txt"
  rm -f "$tmp_target"

  prompt="Run exactly these two shell commands, in order, and nothing else. \
Do not create, read or modify any other file, and do not ask me anything. \
1. printf '%s' $MARKER > $home_target \
2. printf '%s' $MARKER > $tmp_target \
Then stop and reply with the single word DONE."

  exit_code=0
  ( cd "$work" && CODEX_HOME="$home" run_with_timeout "$BIN" exec --json \
      --skip-git-repo-check ${FLAGS[@]+"${FLAGS[@]}"} "$prompt" ) \
    > "$OUT/$name.jsonl" 2> "$OUT/$name.stderr" || exit_code=$?

  wrote_home="no"; grep -q "$MARKER" "$home_target" 2>/dev/null && wrote_home="yes"
  wrote_tmp="no";  grep -q "$MARKER" "$tmp_target"  2>/dev/null && wrote_tmp="yes"

  echo "-- $name  [$(expand_flags | tr '\n' ' ')]"
  echo "   exit=$exit_code  wrote_outside_home=$wrote_home  wrote_outside_tmp=$wrote_tmp"
  python3 "$SUMMARY" "$OUT/$name.jsonl" | sed 's/^/   /'
  echo
done

# ---------------------------------------------------------------------------

BASELINE_HOME="$HOME/.lazy-harness-$MARKER-baseline.txt"
if grep -q "$MARKER" "$BASELINE_HOME" 2>/dev/null; then
  echo "!! CONTROL FAILED: the no-flags run wrote outside the workspace."
  echo "   There was no sandbox to bypass on this machine — check ~/.codex for a"
  echo "   config that already sets sandbox_mode or approval_policy, and re-run"
  echo "   with CODEX_HOME pointed somewhere clean. Every row above says nothing"
  echo "   about bypass until this passes."
  echo
fi

cat <<EOF
== done ==

Artifacts under: $OUT
(the \$HOME markers are removed on exit; the JSONL streams are not)

Paste into specs/designs/codex-evidence.md as a new §7 "Bypass levels", one row
per candidate:

  level | flags | observed behaviour | evidence

where "observed behaviour" is the exit code, the two wrote_outside_* verdicts
and the signals block, and "evidence" is [run] for every row this script
produced — the rows it replaces in ADR-049 are marked [help] and must not stay
that way once this has been run.

Then settle ADR-049's three mappings against it:

  ENABLE      "available but off". If no candidate leaves the sandbox on while
              making bypass reachable, Codex has no such position and
              CodexAdapter.bypass_argv returns None for it — a reported state,
              never a silent alias for ACTIVATE.
  ACTIVATE    the cheapest candidate with wrote_outside_home=yes.
  NO_SANDBOX  a separate position only if some candidate turns the sandbox off
              WITHOUT also removing approvals. If the only thing that reaches
              wrote_outside_home=yes is the combined flag, then ACTIVATE and
              NO_SANDBOX collapse to one spelling on this agent, and the ADR
              says which one returns None rather than shipping two names for it.
EOF
