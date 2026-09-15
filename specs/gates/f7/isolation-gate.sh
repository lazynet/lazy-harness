#!/usr/bin/env bash
# F7 isolation gate — does a hook invoked with `--profile <p>` write its
# evidence under that profile's config dir, and nowhere else?
#
# That is the whole question. Sections A, B and C of the original step 4 gate
# are settled and are not re-run here.
#
# SCOPE IS DERIVED, NOT TYPED. The asserted set is every builtin the registry
# marks `migrated=True` (`hooks/loader.py`, read through the public
# `list_builtin_hooks()` + `builtin_migrated()`), minus the skip list below.
# The known-gap set is every builtin it marks `migrated=False`. An unmigrated
# builtin reaches `main()` through `cli/hooks_cmd.py`'s unmigrated branch, which
# calls `main_fn()` with NO arguments — the `--profile` click option is parsed
# and discarded — and which assumes Claude Code's wire format outright
# (`loader.PRE_RUNNER_AGENT`). It has no profile to honour, so it is counted,
# not failed. Deriving both lists is the point: the gap set empties itself as
# the migrations land, and this script cannot drift from the registry the way a
# hand-typed list did (it claimed three migrated when eight were).
#
# TWO HOOKS ARE SKIPPED, AND BOTH REASONS ARE NON-OBVIOUS:
#
#   stop-verify-guard is migrated but writes NO line to any file under the
#   agent runtime dir. Its only sink is the metrics DB via
#   `monitoring.db.resolve_db_path()`, which is scoped by LH_DATA_DIR and not
#   by the agent runtime dir. It has no site in this gate's scope.
#
#   engram-persist is migrated and writes no `hooks.log` line either, but it is
#   NOT skipped: it writes `engram_persist_metrics.jsonl` under the profile's
#   logs dir, carrying the cwd basename as `project_key`. That is a second
#   evidence channel, and WATCHED_LOGS covers it.
#
# pre-compact is migrated and IS invoked here. It was absent from the step 4
# counts only because that gate never called it — not because it was clean.
#
# Usage:
#   ./isolation-gate.sh [path-to-lh]        (default: lh on PATH)
# Env:
#   F7_GATE_ROOT    parent dir for the run tree   (default: a fresh mktemp -d)
#   F7_GATE_PYTHON  interpreter used to read the registry (default: the
#                   interpreter beside $LH_BIN — a uv tool install ships one)
# Exit:
#   0 = PASS, 1 = FAIL, 2 = harness error (could not set up or could not derive)

# `-e` is OFF DELIBERATELY. This gate counts failures and keeps going: a failed
# assertion calls fail() and the run continues so the report names every leak,
# not just the first. Turning on `-e` (as the repo's shell convention otherwise
# requires) would abort at the first non-zero grep and silently break the
# counting. Do not "fix" this line.
set -uo pipefail

LH_BIN="${1:-lh}"
command -v "$LH_BIN" >/dev/null 2>&1 || { echo "harness error: $LH_BIN not executable" >&2; exit 2; }

ROOT="${F7_GATE_ROOT:-$(mktemp -d -t f7-gate)}"
[ -d "$ROOT" ] || { echo "harness error: F7_GATE_ROOT=$ROOT is not a directory" >&2; exit 2; }
RUN_TOKEN="f7gate$(date +%s)$$"
RUN="$ROOT/run-$RUN_TOKEN"

PROFILE=gate-throwaway
PROFILE_DIR="$RUN/profile-codex"      # the ONLY dir allowed to receive evidence
GLOBAL_SCRATCH="$RUN/global-claude"   # stands in for the live global dir
FAKE_HOME="$RUN/home"                 # contains the `~/.<agent>` last resort
LH_CFG="$RUN/lhconfig"
LH_DATA="$RUN/lhdata"
LH_CACHE="$RUN/lhcache"
FIXTURES="$RUN/fixtures"

# ---------------------------------------------------------------------------
# BLAST RADIUS. This gate is meant to be run against a BROKEN build, where the
# leak is real, so the leak is aimed somewhere harmless before it happens:
#
#   CLAUDE_CONFIG_DIR -> $GLOBAL_SCRATCH   (not ~/.claude-lazy / ~/.claude-flex)
#   HOME              -> $FAKE_HOME        (so the `~/.codex` last resort is fake)
#   LH_CONFIG_DIR / LH_DATA_DIR / LH_CACHE_DIR -> under $RUN
#
# $GLOBAL_SCRATCH is what the assertions treat as "the global dir": a line
# landing there is a LEAK, exactly as a line in ~/.claude-lazy would be. The
# four real directories are still fingerprinted, as a check on this script
# rather than on the build.
#
# PATH is /usr/bin:/bin on purpose: it excludes ruff and ansible-lint, which
# live in ~/.local/bin. That is what drives post-tool-use-format and
# post-tool-use-ansible-lint down their binary-missing branches, the only
# branches on which they log at all.
# ---------------------------------------------------------------------------
REAL_HOME="${HOME}"
REAL_WATCH=(
  "$REAL_HOME/.claude-lazy"
  "$REAL_HOME/.claude-flex"
  "$REAL_HOME/.codex"
  "$REAL_HOME/.config/lazy-harness"
)
CHILD_PATH=/usr/bin:/bin

# The evidence channels. The run-local dirs are grepped whole — they are fresh
# and small, so a sink filename nobody anticipated is still caught. The REAL
# dirs are filtered to these names instead: ~/.claude-lazy holds gigabytes of
# session transcripts and a recursive grep over it would dominate the runtime.
# That asymmetry is safe because the blast radius above redirects every global
# write into $GLOBAL_SCRATCH, which IS grepped whole.
WATCHED_LOGS=(hooks.log engram_persist.log engram_persist_metrics.jsonl)

# --- deriving the scope from the registry ----------------------------------
# A uv tool install puts `python3` beside `lh` in the venv's bin dir, so the
# interpreter that can import the build under test is $(dirname $LH_BIN)/python3.
# F7_GATE_PYTHON overrides it — needed by the fake-lh-*.sh fixtures, which are
# shell scripts with no interpreter of their own.
derive_python() {
  local cand
  for cand in "${F7_GATE_PYTHON:-}" "$(dirname "$(command -v "$LH_BIN")")/python3"; do
    [ -n "$cand" ] && [ -x "$cand" ] || continue
    "$cand" -c 'import lazy_harness' >/dev/null 2>&1 && { echo "$cand"; return 0; }
  done
  return 1
}

GATE_PYTHON="$(derive_python)" || {
  echo "harness error: no interpreter able to import lazy_harness." >&2
  echo "  tried: \${F7_GATE_PYTHON} and $(dirname "$(command -v "$LH_BIN")")/python3" >&2
  echo "  the asserted and known-gap hook sets are DERIVED from the registry;" >&2
  echo "  without it this gate would have to guess, so it refuses instead." >&2
  exit 2
}

# `list_builtin_hooks` + `builtin_migrated` are the public read side of
# `_BUILTIN_HOOKS`. Going through them rather than the private dict keeps this
# working against a shipped binary whose internals have moved on.
REGISTRY="$("$GATE_PYTHON" -c '
from lazy_harness.hooks.loader import builtin_migrated, list_builtin_hooks
for name in sorted(list_builtin_hooks()):
    print(name, "migrated" if builtin_migrated(name) else "gap")
' 2>/dev/null)"
[ -n "$REGISTRY" ] || { echo "harness error: registry query returned nothing" >&2; exit 2; }

# Migrated but with no observable sink under the agent runtime dir. See the
# header: this is a property of the hook, not an exemption from the contract.
SKIPPED_HOOKS=(stop-verify-guard)
is_skipped() { case " ${SKIPPED_HOOKS[*]} " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

declare -a ASSERTED_HOOKS=() KNOWN_GAP_HOOKS=()
while read -r name state; do
  [ -n "$name" ] || continue
  if [ "$state" = migrated ]; then
    is_skipped "$name" || ASSERTED_HOOKS+=("$name")
  else
    KNOWN_GAP_HOOKS+=("$name")
  fi
done <<< "$REGISTRY"

FAILURES=0
declare -a FAIL_LINES=()
declare -a GAP_LINES=()

fail() { FAILURES=$((FAILURES + 1)); FAIL_LINES+=("$1"); echo "  FAIL: $1"; }
ok()   { echo "  ok:   $1"; }
info() { echo "  --    $1"; }
gap()  { GAP_LINES+=("$1"); echo "  GAP:  $1"; }

# --- fingerprinting --------------------------------------------------------
watched_files() {
  local d="$1" name
  [ -e "$d" ] || return 0
  for name in "${WATCHED_LOGS[@]}"; do
    find "$d" -type f -name "$name" 2>/dev/null
  done | sort
}

fingerprint() {
  local d="$1" f
  if [ ! -e "$d" ]; then echo "ABSENT"; return 0; fi
  echo "mtime=$(stat -f '%m' "$d" 2>/dev/null || stat -c '%Y' "$d" 2>/dev/null || echo '?')"
  while read -r f; do
    [ -n "$f" ] && printf '%s|%s\n' "$f" "$(wc -l < "$f" | tr -d ' ')"
  done < <(watched_files "$d")
}

# Token hits: the attribution that survives a live profile being written to by
# a concurrent agent session. A raw line-count delta on ~/.claude-lazy is noise
# (the operator's own session fires hooks); a line carrying THIS run's token is not.
#
# `whole` greps every regular file under $d. Used for the run-local dirs, so a
# hook that logs to a filename this gate has never heard of is still caught.
token_hits_whole() {
  local d="$1"
  [ -e "$d" ] || return 0
  grep -rHn --binary-files=without-match -- "$RUN_TOKEN" "$d" 2>/dev/null
}

# `named` greps only WATCHED_LOGS. Used for the real dirs; see WATCHED_LOGS.
token_hits_named() {
  local d="$1" f
  [ -e "$d" ] || return 0
  while read -r f; do
    [ -n "$f" ] && grep -Hn -- "$RUN_TOKEN" "$f" 2>/dev/null
  done < <(watched_files "$d")
}

setup() {
  mkdir -p "$PROFILE_DIR" "$GLOBAL_SCRATCH" "$FAKE_HOME" "$LH_CFG" "$LH_DATA" \
           "$LH_CACHE" "$FIXTURES" \
    || { echo "harness error: cannot create $RUN" >&2; exit 2; }
}

# `[agent].type` stays claude-code while the throwaway profile declares
# agent = "codex". A build that resolves the agent globally therefore picks the
# WRONG adapter, and the wrong adapter reads the wrong env var. Without that
# divergence a global read and a per-profile read give the same answer and the
# gate proves nothing.
write_config() {
  local scenario="$1"
  case "$scenario" in
    missing) rm -f "$LH_CFG/config.toml"; return 0 ;;
    broken)  printf 'this is not = = toml [[[\n' > "$LH_CFG/config.toml"; return 0 ;;
  esac
  local cl_enabled=true
  [ "$scenario" = "disabled" ] && cl_enabled=false
  cat > "$LH_CFG/config.toml" <<EOF
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "$PROFILE"

[profiles.$PROFILE]
config_dir = "$PROFILE_DIR"
agent = "codex"

[compound_loop]
enabled = $cl_enabled

[context_inject]
enabled = true
EOF
}

# --- invocation ------------------------------------------------------------
# Each invocation gets a unique, unrepeatable cwd, used both as the process cwd
# (an unmigrated hook logs `Path.cwd()`) and in the payload (a migrated one logs
# `event.cwd`). Hooks that log neither get the token through a fixture path.
invoke() {
  local hook="$1" scenario="$2" mode="$3" payload="$4"
  local tag="$RUN_TOKEN-$scenario-$mode-$hook"
  local cwd="$RUN/cwd/$tag"
  mkdir -p "$cwd"
  payload="${payload//__CWD__/$cwd}"
  payload="${payload//__TAG__/$tag}"

  local -a env_args=(
    "HOME=$FAKE_HOME"
    "PATH=$CHILD_PATH"
    "LH_CONFIG_DIR=$LH_CFG"
    "LH_DATA_DIR=$LH_DATA"
    "LH_CACHE_DIR=$LH_CACHE"
    "CLAUDE_CONFIG_DIR=$GLOBAL_SCRATCH"
  )
  # mode `codexhome`: the profile's agent env var is set and points at the
  #   profile dir — a build reading the RIGHT adapter lands there.
  # mode `noenv`: no CODEX_HOME at all, which is the state the original gate
  #   measured in a real hook subprocess. A correct build must fall through to
  #   the profile's own `config_dir`; a wrong one falls through to `~/.codex`.
  [ "$mode" = "codexhome" ] && env_args+=("CODEX_HOME=$PROFILE_DIR")

  ( cd "$cwd" && printf '%s' "$payload" | env -i "${env_args[@]}" \
      "$LH_BIN" hook "$hook" --profile "$PROFILE" >/dev/null 2>&1 )
  return 0
}

# --- per-hook payloads -----------------------------------------------------
# Most hooks log the cwd, so the default payload carries the token there. The
# four that log only on a rare branch each get the fixture that reaches it: an
# over-threshold MEMORY.md write, an offsetless Read of a 600-line file, a .py
# edit with ruff off PATH, and a playbook edit with ansible-lint off PATH.
# A hook with no case here still runs on the default payload — and if it is
# asserted and logs nothing, the gate fails loudly rather than skipping it.
payload_for() {
  local hook="$1" scenario="$2" mode="$3"
  local tag="$RUN_TOKEN-$scenario-$mode-$hook"
  case "$hook" in
    context-inject)
      printf '{"cwd":"__CWD__","session_id":"%s"}' "$RUN_TOKEN" ;;
    # The security hook logs the COMMAND, not the cwd, so the token rides
    # inside the command text.
    pre-tool-use-security|pre-tool-use-git-scope)
      printf '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/__TAG__-secblock"}}' ;;
    pre-tool-use-memory-size)
      mkdir -p "$FIXTURES/$tag/memory"
      printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"%s"}}' \
        "$FIXTURES/$tag/memory/MEMORY.md" "$(python3 -c 'print("x\\n"*300, end="")')" ;;
    pre-tool-use-read-size)
      mkdir -p "$FIXTURES/$tag"
      python3 -c "open('$FIXTURES/$tag/big.txt','w').write('line\n'*600)"
      printf '{"tool_name":"Read","tool_input":{"file_path":"%s"}}' "$FIXTURES/$tag/big.txt" ;;
    post-tool-use-format)
      mkdir -p "$FIXTURES/$tag"; : > "$FIXTURES/$tag/mod.py"
      printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"}}' "$FIXTURES/$tag/mod.py" ;;
    post-tool-use-ansible-lint)
      mkdir -p "$FIXTURES/$tag/playbooks"; : > "$FIXTURES/$tag/ansible.cfg"
      printf -- "- hosts: all\n" > "$FIXTURES/$tag/playbooks/site.yml"
      printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"}}' \
        "$FIXTURES/$tag/playbooks/site.yml" ;;
    post-tool-use-sync-claude)
      mkdir -p "$FIXTURES/$tag"; : > "$FIXTURES/$tag/CLAUDE.md"
      printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"}}' "$FIXTURES/$tag/CLAUDE.md" ;;
    user-prompt-goal)
      printf '{"cwd":"__CWD__","prompt":"__TAG__"}' ;;
    *)
      printf '{"cwd":"__CWD__"}' ;;
  esac
}

# The string that attributes an entry to one hook in one scenario/mode. Default
# is the tag, which rides in the cwd; the security hooks put it in the command.
needle_for() {
  local hook="$1" tag="$2"
  case "$hook" in
    pre-tool-use-security|pre-tool-use-git-scope) printf '%s-secblock' "$tag" ;;
    *) printf '%s' "$tag" ;;
  esac
}

run_set() {
  local scenario="$1" mode="$2" hook
  shift 2
  for hook in "$@"; do
    invoke "$hook" "$scenario" "$mode" "$(payload_for "$hook" "$scenario" "$mode")"
  done
}

# ---------------------------------------------------------------------------
echo "F7 isolation gate"
echo "binary:  $LH_BIN  ($("$LH_BIN" --version 2>&1 | tail -1))"
echo "python:  $GATE_PYTHON  (registry source)"
echo "run:     $RUN"
echo "token:   $RUN_TOKEN"
echo "profile: $PROFILE  (agent = codex; global [agent].type = claude-code)"
echo "asserted (migrated, derived): ${ASSERTED_HOOKS[*]:-(none)}"
echo "known gap (unmigrated, derived): ${KNOWN_GAP_HOOKS[*]:-(none)}"
echo "skipped: ${SKIPPED_HOOKS[*]} — migrated, but no sink under the agent runtime dir"
echo "watched: ${WATCHED_LOGS[*]}"
echo

[ "${#ASSERTED_HOOKS[@]}" -gt 0 ] || {
  echo "harness error: nothing to assert — every migrated builtin is skipped" >&2
  exit 2
}

setup

echo "== fingerprint BEFORE =="
declare -A BEFORE
for d in "${REAL_WATCH[@]}" "$GLOBAL_SCRATCH" "$FAKE_HOME" "$PROFILE_DIR"; do
  BEFORE["$d"]="$(fingerprint "$d")"
  n=$(printf '%s' "${BEFORE[$d]}" | grep -c '|' || true)
  echo "  $d  ($n watched file(s))"
done
echo

# HARD scenarios: the config loads, so the profile -> config_dir mapping is in
#   hand and a correct build MUST use it. `disabled` is here because
#   compound-loop and session-end take an early-return branch on it — measured:
#   they still emit their `fired cwd=` line first, so the assertion holds.
# DEGRADED scenarios: no config, or one that will not parse. There is no
#   profiles table to read, so even a correct build falls back to the global
#   agent. Recorded, not asserted.
HARD_SCENARIOS=(full disabled)
SOFT_SCENARIOS=(missing broken)
MODES=(codexhome noenv)

# The hard scenarios run FIRST and alone, so a degraded-path line — expected in
# the global fallback even after the fix — cannot be mistaken for a leak.
for scenario in "${HARD_SCENARIOS[@]}"; do
  write_config "$scenario"
  for mode in "${MODES[@]}"; do
    run_set "$scenario" "$mode" "${ASSERTED_HOOKS[@]}"
  done
done

echo "== section 10: migrated hooks land under the profile's config dir =="
PROFILE_HITS="$(token_hits_whole "$PROFILE_DIR")"
for scenario in "${HARD_SCENARIOS[@]}"; do
  for mode in "${MODES[@]}"; do
    for hook in "${ASSERTED_HOOKS[@]}"; do
      needle="$(needle_for "$hook" "$RUN_TOKEN-$scenario-$mode-$hook")"
      if printf '%s\n' "$PROFILE_HITS" | grep -q -- "$needle"; then
        ok "$scenario/$mode $hook -> profile dir"
      else
        where="$( { token_hits_whole "$GLOBAL_SCRATCH"; token_hits_whole "$FAKE_HOME"; } \
                  | grep -- "$needle" | head -1 )"
        [ -z "$where" ] && where="(no entry written anywhere the gate watches)"
        fail "$scenario/$mode $hook did not reach $PROFILE_DIR; found: $where"
      fi
    done
  done
done
echo

echo "== section 11: nothing moved outside the profile's config dir =="
# 11a — the absence assertion, by token. The one that matters.
for d in "$GLOBAL_SCRATCH" "$FAKE_HOME"; do
  hits="$(token_hits_whole "$d")"
  if [ -z "$hits" ]; then
    ok "no $RUN_TOKEN entries under $d"
  else
    while IFS= read -r h; do
      [ -n "$h" ] && fail "leaked entry outside the profile dir -> $h"
    done <<< "$hits"
  fi
done
for d in "${REAL_WATCH[@]}"; do
  hits="$(token_hits_named "$d")"
  if [ -z "$hits" ]; then
    ok "no $RUN_TOKEN entries under $d"
  else
    while IFS= read -r h; do
      [ -n "$h" ] && fail "leaked entry outside the profile dir -> $h"
    done <<< "$hits"
  fi
done

# 11b — absence by line count, on dirs with no other writer.
for d in "$GLOBAL_SCRATCH" "$FAKE_HOME"; do
  after="$(fingerprint "$d")"
  before_counts="$(printf '%s' "${BEFORE[$d]}" | grep '|' | sort || true)"
  after_counts="$(printf '%s' "$after" | grep '|' | sort || true)"
  if [ "$before_counts" = "$after_counts" ]; then
    ok "watched-file line counts unchanged under $d"
  else
    fail "watched-file line counts changed under $d:"
    diff <(printf '%s\n' "$before_counts") <(printf '%s\n' "$after_counts") | sed 's/^/        /'
  fi
done

# 11c — the real dirs, as a check on this script's containment rather than on
# the build. Not a count assertion: ~/.claude-lazy is a LIVE profile whose
# hooks.log grows from the operator's own session while the gate runs. 11a
# covers them by token, which survives concurrent writers.
for d in "${REAL_WATCH[@]}"; do
  after="$(fingerprint "$d")"
  if [ "$after" = "${BEFORE[$d]}" ]; then
    ok "untouched (mtime + counts): $d"
  else
    info "changed while the gate ran: $d — expected on a live profile; 11a is the binding check"
  fi
done
echo

# --- recorded, never asserted ----------------------------------------------
echo "== degraded config paths (recorded, not asserted) =="
# No config / unparseable config: there is no profiles table, so the
# profile -> config_dir mapping does not exist and the global fallback is
# correct behaviour, not a regression. Recorded so a future change of that
# contract is visible rather than silent.
for scenario in "${SOFT_SCENARIOS[@]}"; do
  write_config "$scenario"
  for mode in "${MODES[@]}"; do
    run_set "$scenario" "$mode" "${ASSERTED_HOOKS[@]}"
    for hook in "${ASSERTED_HOOKS[@]}"; do
      needle="$(needle_for "$hook" "$RUN_TOKEN-$scenario-$mode-$hook")"
      loc="$( { token_hits_whole "$PROFILE_DIR"; token_hits_whole "$GLOBAL_SCRATCH"; \
                token_hits_whole "$FAKE_HOME"; } | grep -- "$needle" | head -1 | cut -d: -f1 )"
      info "$scenario/$mode $hook -> ${loc:-(nowhere)}"
    done
  done
done
echo

echo "== KNOWN GAP — unmigrated builtins, tracked to step 5, NOT asserted =="
if [ "${#KNOWN_GAP_HOOKS[@]}" -eq 0 ]; then
  echo "  (empty — every builtin in the registry is migrated)"
  GAP_TOTAL=0
else
  echo "  These reach main() with no arguments (cli/hooks_cmd.py unmigrated branch)"
  echo "  and assume Claude Code's wire format (loader.PRE_RUNNER_AGENT). They have"
  echo "  no profile to honour, so they are counted here, not failed. A PASS below"
  echo "  means the MIGRATED hooks are isolated — it does NOT mean nothing leaks."
  for scenario in "${HARD_SCENARIOS[@]}"; do
    write_config "$scenario"
    for mode in "${MODES[@]}"; do
      run_set "$scenario" "$mode" "${KNOWN_GAP_HOOKS[@]}"
    done
  done
  GAP_TOTAL=0
  for hook in "${KNOWN_GAP_HOOKS[@]}"; do
    n=$( { token_hits_whole "$GLOBAL_SCRATCH"; token_hits_whole "$FAKE_HOME"; } \
         | grep -c -- "-$hook" || true )
    GAP_TOTAL=$((GAP_TOTAL + n))
    gap "$hook — $n entr(y/ies) leaked outside the profile dir"
  done
  gap "TOTAL unmigrated entries leaked: $GAP_TOTAL"
fi
echo

if [ "$FAILURES" -eq 0 ]; then
  echo "PASS — migrated hook evidence stays inside the profile that invoked them"
  echo "       (known gap still open: $GAP_TOTAL unmigrated entr(y/ies) leaked — step 5)"
  echo "       evidence: $RUN"
  exit 0
fi
echo "FAIL — $FAILURES assertion(s) failed"
printf '%s\n' "${FAIL_LINES[@]}" | sed 's/^/  * /'
echo "known gap (not counted above): $GAP_TOTAL unmigrated entr(y/ies) leaked — step 5"
echo "evidence kept under: $RUN"
exit 1
