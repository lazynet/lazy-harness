#!/usr/bin/env bash
# F7 isolation gate — does a hook invoked with `--profile <p>` write its
# evidence under that profile's config dir, and nowhere else?
#
# That is the whole question, and it is the ONLY question. Sections A, B and C
# of the original step 4 gate are settled and are not re-run here.
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
# ---------------------------------------------------------------------------
# TWO LANES, ALSO DERIVED. THIS IS THE 2026-09-15 REPAIR.
# ---------------------------------------------------------------------------
# Until this commit the gate ran ONE throwaway profile declaring
# `agent = "codex"`, and fed every hook a Claude Code payload. Since step 5 the
# parse goes through the INVOKED PROFILE's adapter, and
# `CodexAdapter._TOOL_OPERATIONS` (`codex.py:92`) maps exactly one tool —
# `Bash -> RUN_COMMAND`. Measured against the shipped adapters:
#
#   codex  {"tool_name":"Edit","tool_input":{"file_path":"/a/b.py"}}
#          -> ToolCall(native_name='Edit', operation=None, edits=())
#   claude -> ToolCall(native_name='Edit', operation=MODIFY_FILE,
#                      edits=(FileEdit(path=/a/b.py),))
#
# A correctly migrated hook abstains on that empty `ToolCall` and writes
# nothing — `post_tool_use_format.py:32` returns on `operation is not
# MODIFY_FILE`. Section 10 read "wrote nothing" as a leak and failed the hook
# for honouring its own contract. The gate was suppressing the evidence it
# measures.
#
# The repair splits the question in two rather than widening it. Each lane
# keeps a global-vs-profile divergence, which is what makes a per-profile
# resolution distinguishable from a global one; without a divergence both
# resolutions give the same path and the gate proves nothing.
#
#   codex lane   profile declares `agent = "codex"`, global `[agent].type`
#                stays `claude-code`. Every migrated builtin that declares NO
#                `operations` — a lifecycle hook, whose payload crosses both
#                adapters losslessly. The divergence is the ADAPTER: a build
#                resolving the agent globally picks claude-code, reads
#                CLAUDE_CONFIG_DIR, and lands in $GLOBAL_SCRATCH.
#
#   claude lane  profile declares `agent = "claude-code"` with its own
#                `config_dir`. Every builtin that declares `operations`, i.e.
#                reads `event.tool`. The divergence is the CONFIG_DIR: a build
#                that throws the invoked profile away falls through to
#                `ClaudeCodeAdapter.global_config_link()` — `Path.home()/
#                ".claude"`, read at call time — and lands in
#                $FAKE_HOME/.claude. Section 11 observes that, which is the
#                half that matters.
#
# `BuiltinHookSpec.operations` is the discriminator because it is the registry's
# own answer to "does this hook look at tool calls": *"Empty means a hook that
# does not look at tool calls at all."* It is read off `_BUILTIN_HOOKS`, the one
# private read in this script — there is no public `builtin_operations()` yet,
# and `tests/unit/test_hook_matcher_coverage.py:82` keys its subject list the
# same way for the same reason (PR #320). If that dict ever moves, the registry
# query below returns nothing and the gate exits 2 rather than guessing.
#
# WHAT THIS GATE DELIBERATELY DOES NOT MEASURE: the translation itself. Giving
# each hook a payload in its own agent's dialect would make one script answer
# two questions behind one exit code, and a red run could not say which
# property broke. That second gate is worth having and is recorded as future
# work in `specs/backlog.md`.
#
# ---------------------------------------------------------------------------
# SIX HOOKS ARE SKIPPED, AND EVERY REASON IS THE SAME ONE: no sink under the
# agent runtime dir, so this gate has no site to observe. Verified per hook, by
# reading the sink rather than by one run coming up empty:
#
#   stop-verify-guard        only sink is the metrics DB via
#                            `monitoring.db.resolve_db_path()`
#                            (`stop_verify_guard.py:65-67`), scoped by
#                            LH_DATA_DIR, not by the agent runtime dir.
#   user-prompt-goal         same sink, same scoping (`user_prompt_goal.py:73`
#                            -> `resolve_db_path()`).
#   herdr-context-gauge      only sink is a throttle stamp under
#                            `tempfile.gettempdir()`
#                            (`herdr_context_gauge.py:123`).
#   stop-context-rotate      only sink is a once-per-session stamp under
#                            `tempfile.gettempdir()`
#                            (`stop_context_rotate.py:48`).
#   session-start-preflight  writes NOTHING. It resolves the agent dir per
#                            profile (`session_start_preflight.py:220`) only to
#                            READ `.credentials.json`, and answers on stdout
#                            (`:242`). Its per-profile resolution is real and
#                            worth asserting — through the stdout channel, which
#                            is not this gate's. Recorded in `specs/backlog.md`.
#   post-tool-use-sync-claude  writes NOTHING under the agent runtime dir, and
#                            says so itself: *"The directory half is unused:
#                            this hook writes nothing under the agent's runtime
#                            dir"* (`post_tool_use_sync_claude.py:97-99`). It
#                            takes the ADAPTER half of `agent_dir_for` for
#                            `system_doc_name()` and writes into the segment
#                            tree, `<profiles_dir>/<profile>/CLAUDE.md`
#                            (`core/sync_agent_md.py:79`). Zero `hooks.log`
#                            sites. Migrated in PR #324, after the backlog entry
#                            was written, which is why that entry does not name
#                            it. Same future work as the preflight: assertable,
#                            through a channel this gate does not watch.
#
# `specs/backlog.md` previously said these hooks "sí tienen sink bajo el agent
# runtime dir, a diferencia de `stop-verify-guard`". That is false for all six,
# and asserting on them made the gate fail for something it cannot see — which
# is the same "two questions, one exit code" problem as the lane split. Skipping
# them here is the gate's own documented criterion applied consistently, not an
# exemption from the contract.
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

# The two throwaway profiles. Both config dirs are the ONLY places allowed to
# receive their own lane's evidence — and neither may receive the other's,
# which is section 11d.
PROFILE_CODEX=gate-throwaway-codex
PROFILE_CLAUDE=gate-throwaway-claude
PROFILE_CODEX_DIR="$RUN/profile-codex"
PROFILE_CLAUDE_DIR="$RUN/profile-claude"

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
#                                          — CODEX LANE ONLY, see below
#   HOME              -> $FAKE_HOME        (so the `~/.<agent>` last resort is fake)
#   LH_CONFIG_DIR / LH_DATA_DIR / LH_CACHE_DIR -> under $RUN
#
# $GLOBAL_SCRATCH is what the assertions treat as "the global dir": a line
# landing there is a LEAK, exactly as a line in ~/.claude-lazy would be. The
# four real directories are still fingerprinted, as a check on this script
# rather than on the build.
#
# CLAUDE_CONFIG_DIR CANNOT DOUBLE AS THE SHIELD IN THE CLAUDE LANE. It is that
# lane's own adapter env var, and step 1 of `agent_runtime_dir` answers from it
# before the profile is ever consulted — setting it would pre-empt the very
# resolution the lane exists to measure. So the claude lane leaves it unset in
# `noenv` mode, and containment comes from HOME instead: `global_config_link()`
# is `Path.home()/".claude"` evaluated at call time, so a globally-resolving
# build lands in $FAKE_HOME/.claude, which section 11a greps whole.
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
  "$REAL_HOME/.claude"
  "$REAL_HOME/.config/lazy-harness"
)
CHILD_PATH=/usr/bin:/bin

# The evidence channels. The run-local dirs are grepped whole — they are fresh
# and small, so a sink filename nobody anticipated is still caught. The REAL
# dirs are filtered to these names instead: ~/.claude-lazy holds gigabytes of
# session transcripts and a recursive grep over it would dominate the runtime.
# That asymmetry is safe because the blast radius above redirects every global
# write into $GLOBAL_SCRATCH or $FAKE_HOME, both of which ARE grepped whole.
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
  echo "  the asserted set, the known-gap set and the lane split are all DERIVED" >&2
  echo "  from the registry; without it this gate would have to guess, so it" >&2
  echo "  refuses instead." >&2
  exit 2
}

# `list_builtin_hooks` + `builtin_migrated` are the public read side of
# `_BUILTIN_HOOKS`. Going through them rather than the private dict keeps this
# working against a shipped binary whose internals have moved on. `operations`
# has no public reader yet, so the lane comes off the spec directly — the one
# private read here, and the reason a missing `_BUILTIN_HOOKS` must exit 2.
REGISTRY="$("$GATE_PYTHON" -c '
from lazy_harness.hooks.loader import _BUILTIN_HOOKS, builtin_migrated, list_builtin_hooks
for name in sorted(list_builtin_hooks()):
    spec = _BUILTIN_HOOKS[name]
    state = "migrated" if builtin_migrated(name) else "gap"
    # Declared operations = "this hook reads event.tool". Its dialect has to
    # survive the adapter, so it runs in the claude lane.
    lane = "claude" if spec.operations else "codex"
    print(name, state, lane)
' 2>/dev/null)"
[ -n "$REGISTRY" ] || { echo "harness error: registry query returned nothing" >&2; exit 2; }

# Migrated, but with NO sink under the agent runtime dir. See the header for the
# verified sink of each: this is a property of the hook, not an exemption from
# the contract.
SKIPPED_HOOKS=(
  stop-verify-guard
  user-prompt-goal
  herdr-context-gauge
  stop-context-rotate
  session-start-preflight
  post-tool-use-sync-claude
)
is_skipped() { case " ${SKIPPED_HOOKS[*]} " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

declare -a CODEX_LANE=() CLAUDE_LANE=() KNOWN_GAP_CODEX=() KNOWN_GAP_CLAUDE=()
while read -r name state lane; do
  [ -n "$name" ] || continue
  if [ "$state" = migrated ]; then
    is_skipped "$name" && continue
    [ "$lane" = claude ] && CLAUDE_LANE+=("$name") || CODEX_LANE+=("$name")
  else
    [ "$lane" = claude ] && KNOWN_GAP_CLAUDE+=("$name") || KNOWN_GAP_CODEX+=("$name")
  fi
done <<< "$REGISTRY"

LANES=(codex claude)
lane_profile() { case "$1" in codex) printf '%s' "$PROFILE_CODEX" ;; claude) printf '%s' "$PROFILE_CLAUDE" ;; esac; }
lane_dir()     { case "$1" in codex) printf '%s' "$PROFILE_CODEX_DIR" ;; claude) printf '%s' "$PROFILE_CLAUDE_DIR" ;; esac; }
other_lane()   { case "$1" in codex) printf 'claude' ;; claude) printf 'codex' ;; esac; }
lane_hooks()   { case "$1" in codex) printf '%s\n' "${CODEX_LANE[@]:-}" ;; claude) printf '%s\n' "${CLAUDE_LANE[@]:-}" ;; esac; }
lane_gap()     { case "$1" in codex) printf '%s\n' "${KNOWN_GAP_CODEX[@]:-}" ;; claude) printf '%s\n' "${KNOWN_GAP_CLAUDE[@]:-}" ;; esac; }

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
  mkdir -p "$PROFILE_CODEX_DIR" "$PROFILE_CLAUDE_DIR" "$GLOBAL_SCRATCH" \
           "$FAKE_HOME" "$LH_CFG" "$LH_DATA" "$LH_CACHE" "$FIXTURES" \
    || { echo "harness error: cannot create $RUN" >&2; exit 2; }
}

# `[agent].type` stays claude-code, and the codex lane's profile declares
# agent = "codex" against it: a build that resolves the agent globally therefore
# picks the WRONG adapter there, and the wrong adapter reads the wrong env var.
# The claude lane's profile agrees with the global type on purpose — its
# divergence is the `config_dir`, which is what section 11 actually observes.
#
# `default` names the CODEX lane deliberately. A build that resolved
# `profiles.default` instead of the invoked profile would put every claude-lane
# line in the codex dir, and section 11d is what sees that.
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
default = "$PROFILE_CODEX"

[profiles.$PROFILE_CODEX]
config_dir = "$PROFILE_CODEX_DIR"
agent = "codex"

[profiles.$PROFILE_CLAUDE]
config_dir = "$PROFILE_CLAUDE_DIR"
agent = "claude-code"

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
  local lane="$1" hook="$2" scenario="$3" mode="$4" payload="$5"
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
  )
  # mode `agentenv`: the lane's agent env var is set and points at that lane's
  #   profile dir — a build reading the RIGHT adapter lands there (step 1 of
  #   `agent_runtime_dir`).
  # mode `noenv`: the lane's agent env var is absent, which is the state the
  #   original gate measured in a real hook subprocess. A correct build must
  #   fall through to the invoked profile's own `config_dir` (step 2); a wrong
  #   one falls through to the global link or `~/.<agent>` (steps 3 and 4).
  case "$lane" in
    codex)
      # Safe here and only here: CODEX_HOME is this lane's env var, so
      # CLAUDE_CONFIG_DIR is free to be the aim point for a build that picks
      # the global adapter by mistake.
      env_args+=("CLAUDE_CONFIG_DIR=$GLOBAL_SCRATCH")
      [ "$mode" = "agentenv" ] && env_args+=("CODEX_HOME=$PROFILE_CODEX_DIR")
      ;;
    claude)
      # CLAUDE_CONFIG_DIR is this lane's OWN env var. See the blast radius note:
      # in `noenv` it must be absent or step 1 answers before the profile is
      # read, and HOME carries the containment instead.
      [ "$mode" = "agentenv" ] && env_args+=("CLAUDE_CONFIG_DIR=$PROFILE_CLAUDE_DIR")
      ;;
  esac

  ( cd "$cwd" && printf '%s' "$payload" | env -i "${env_args[@]}" \
      "$LH_BIN" hook "$hook" --profile "$(lane_profile "$lane")" >/dev/null 2>&1 )
  return 0
}

# --- per-hook payloads -----------------------------------------------------
# Most hooks log the cwd, so the default payload carries the token there. The
# ones that log only on a rare branch each get the fixture that reaches it: an
# over-threshold MEMORY.md write, an offsetless Read of a 600-line file, a .py
# edit with ruff off PATH, and a playbook edit with ansible-lint off PATH.
# A hook with no case here still runs on the default payload — and if it is
# asserted and logs nothing, the gate fails loudly rather than skipping it.
#
# Every payload is in CLAUDE CODE's dialect, on purpose and now safely: the
# lane split guarantees that any hook whose behaviour depends on `event.tool`
# is invoked under a `claude-code` profile, so the dialect matches the adapter
# that parses it. The codex lane only receives hooks that declare no
# operations, which cross both adapters unchanged.
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
  local lane="$1" scenario="$2" mode="$3" hook
  shift 3
  for hook in "$@"; do
    [ -n "$hook" ] || continue
    invoke "$lane" "$hook" "$scenario" "$mode" "$(payload_for "$hook" "$scenario" "$mode")"
  done
}

# ---------------------------------------------------------------------------
echo "F7 isolation gate"
echo "binary:  $LH_BIN  ($("$LH_BIN" --version 2>&1 | tail -1))"
echo "python:  $GATE_PYTHON  (registry source)"
echo "run:     $RUN"
echo "token:   $RUN_TOKEN"
echo "global:  [agent].type = claude-code"
echo "lane codex:  --profile $PROFILE_CODEX  (agent = codex, diverges from global)"
echo "  asserted:  ${CODEX_LANE[*]:-(none)}"
echo "  known gap: ${KNOWN_GAP_CODEX[*]:-(none)}"
echo "lane claude: --profile $PROFILE_CLAUDE (agent = claude-code, diverges by config_dir)"
echo "  asserted:  ${CLAUDE_LANE[*]:-(none)}"
echo "  known gap: ${KNOWN_GAP_CLAUDE[*]:-(none)}"
echo "skipped: ${SKIPPED_HOOKS[*]} — migrated, but no sink under the agent runtime dir"
echo "watched: ${WATCHED_LOGS[*]}"
echo

[ "$(( ${#CODEX_LANE[@]} + ${#CLAUDE_LANE[@]} ))" -gt 0 ] || {
  echo "harness error: nothing to assert — every migrated builtin is skipped" >&2
  exit 2
}
# A lane with no hooks measures nothing, and an empty claude lane is the exact
# regression this repair fixes arriving from the other side: it would mean the
# tool-reading hooks had silently left the asserted set again.
for lane in "${LANES[@]}"; do
  [ -n "$(lane_hooks "$lane" | tr -d '[:space:]')" ] || {
    echo "harness error: lane '$lane' has no asserted hook — the derivation or" >&2
    echo "  the skip list has drifted, and this gate would report PASS on half" >&2
    echo "  the contract. Refusing." >&2
    exit 2
  }
done

setup

echo "== fingerprint BEFORE =="
declare -A BEFORE
for d in "${REAL_WATCH[@]}" "$GLOBAL_SCRATCH" "$FAKE_HOME" "$PROFILE_CODEX_DIR" "$PROFILE_CLAUDE_DIR"; do
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
MODES=(agentenv noenv)

# The hard scenarios run FIRST and alone, so a degraded-path line — expected in
# the global fallback even after the fix — cannot be mistaken for a leak.
for scenario in "${HARD_SCENARIOS[@]}"; do
  write_config "$scenario"
  for lane in "${LANES[@]}"; do
    for mode in "${MODES[@]}"; do
      run_set "$lane" "$scenario" "$mode" $(lane_hooks "$lane")
    done
  done
done

echo "== section 10: migrated hooks land under the invoked profile's config dir =="
declare -A LANE_HITS
for lane in "${LANES[@]}"; do
  LANE_HITS["$lane"]="$(token_hits_whole "$(lane_dir "$lane")")"
done
for lane in "${LANES[@]}"; do
  for scenario in "${HARD_SCENARIOS[@]}"; do
    for mode in "${MODES[@]}"; do
      while read -r hook; do
        [ -n "$hook" ] || continue
        needle="$(needle_for "$hook" "$RUN_TOKEN-$scenario-$mode-$hook")"
        if printf '%s\n' "${LANE_HITS[$lane]}" | grep -q -- "$needle"; then
          ok "$lane $scenario/$mode $hook -> $(lane_profile "$lane") dir"
        else
          where="$( { token_hits_whole "$GLOBAL_SCRATCH"; token_hits_whole "$FAKE_HOME"; \
                      token_hits_whole "$(lane_dir "$(other_lane "$lane")")"; } \
                    | grep -- "$needle" | head -1 )"
          [ -z "$where" ] && where="(no entry written anywhere the gate watches)"
          fail "$lane $scenario/$mode $hook did not reach $(lane_dir "$lane"); found: $where"
        fi
      done < <(lane_hooks "$lane")
    done
  done
done
echo

echo "== section 11: nothing moved outside the invoked profile's config dir =="
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

# 11d — NO CROSS-LANE BLEED. New with the lane split, and the reason it is worth
# having two live profiles rather than one: "wrote under a profile" and "wrote
# under THE INVOKED profile" were indistinguishable while only one profile
# existed. `profiles.default` names the codex lane, so a build resolving the
# default instead of `--profile` would put every claude-lane line in the codex
# dir — which this is what sees.
for lane in "${LANES[@]}"; do
  other="$(other_lane "$lane")"
  intruder=""
  while read -r hook; do
    [ -n "$hook" ] || continue
    for scenario in "${HARD_SCENARIOS[@]}"; do
      for mode in "${MODES[@]}"; do
        needle="$(needle_for "$hook" "$RUN_TOKEN-$scenario-$mode-$hook")"
        hit="$(printf '%s\n' "${LANE_HITS[$other]}" | grep -- "$needle" | head -1)"
        [ -n "$hit" ] && intruder="$hit"
      done
    done
  done < <(lane_hooks "$lane")
  if [ -z "$intruder" ]; then
    ok "no $lane-lane entries under the $other lane's dir"
  else
    fail "$lane-lane entry landed under the $other lane's profile dir -> $intruder"
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
  for lane in "${LANES[@]}"; do
    for mode in "${MODES[@]}"; do
      run_set "$lane" "$scenario" "$mode" $(lane_hooks "$lane")
      while read -r hook; do
        [ -n "$hook" ] || continue
        needle="$(needle_for "$hook" "$RUN_TOKEN-$scenario-$mode-$hook")"
        loc="$( { token_hits_whole "$PROFILE_CODEX_DIR"; token_hits_whole "$PROFILE_CLAUDE_DIR"; \
                  token_hits_whole "$GLOBAL_SCRATCH"; token_hits_whole "$FAKE_HOME"; } \
                | grep -- "$needle" | head -1 | cut -d: -f1 )"
        info "$lane $scenario/$mode $hook -> ${loc:-(nowhere)}"
      done < <(lane_hooks "$lane")
    done
  done
done
echo

echo "== KNOWN GAP — unmigrated builtins, tracked to step 5, NOT asserted =="
GAP_TOTAL=0
if [ "$(( ${#KNOWN_GAP_CODEX[@]} + ${#KNOWN_GAP_CLAUDE[@]} ))" -eq 0 ]; then
  echo "  (empty — every builtin in the registry is migrated)"
else
  echo "  These reach main() with no arguments (cli/hooks_cmd.py unmigrated branch)"
  echo "  and assume Claude Code's wire format (loader.PRE_RUNNER_AGENT). They have"
  echo "  no profile to honour, so they are counted here, not failed. A PASS below"
  echo "  means the MIGRATED hooks are isolated — it does NOT mean nothing leaks."
  echo "  The count is lower than a single-profile run's: an unmigrated hook in the"
  echo "  claude lane's agentenv mode reads CLAUDE_CONFIG_DIR and lands in the"
  echo "  profile dir by accident, which is not a leak even though it is not"
  echo "  obedience either. noenv is the mode that exposes them."
  for scenario in "${HARD_SCENARIOS[@]}"; do
    write_config "$scenario"
    for lane in "${LANES[@]}"; do
      for mode in "${MODES[@]}"; do
        run_set "$lane" "$scenario" "$mode" $(lane_gap "$lane")
      done
    done
  done
  for lane in "${LANES[@]}"; do
    while read -r hook; do
      [ -n "$hook" ] || continue
      n=$( { token_hits_whole "$GLOBAL_SCRATCH"; token_hits_whole "$FAKE_HOME"; } \
           | grep -c -- "-$hook" || true )
      GAP_TOTAL=$((GAP_TOTAL + n))
      gap "$hook ($lane lane) — $n entr(y/ies) leaked outside the profile dir"
    done < <(lane_gap "$lane")
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
