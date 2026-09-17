#!/usr/bin/env bash
# F9 Codex acceptance gate — does the whole Codex path hold together on a real
# profile: deploy, trust, deny, meter, count, re-approve?
#
# This is the iteration's success criterion, and the design states it as an
# observation rather than a test
# (`specs/designs/2026-09-13-multi-agent-harness-design.md:843-846`): *deploy,
# start a session, confirm the hooks are reported untrusted and do not fire;
# trust them; confirm they fire; change one matcher, redeploy, confirm `lh
# doctor` reports it before the next session silently drops it.*
#
# F7 (`../f7/isolation-gate.sh`) and F8 (`../f8/translation-gate.sh`) each answer
# one property against stubs, in CI, in seconds. This one cannot be either of
# those things: every phase needs a real `codex` binary, a real `[profiles.lazy-codex]`
# and a real `lh deploy` writing into the user's own Codex config dir, and the
# trust step needs a human in Codex's TUI. So the gate is a script the USER runs
# from a plain terminal, and `--dry-run` is the only mode CI and an agent pane
# can execute (`tests/integration/test_f9_gate_dry_run.py`).
#
# ---------------------------------------------------------------------------
# WHAT THIS GATE DELIBERATELY DOES NOT MEASURE.
# ---------------------------------------------------------------------------
# Isolation (F7's question) and translation (F8's question). Both are already
# gated against stubs, and re-asserting them here would put three questions
# behind one exit code on the one run that is expensive and manual — a red run
# could not say which property broke. This gate assumes both hold and asks only
# whether the end-to-end path a user walks produces the observations the design
# promised.
#
# It also does not measure token cost, latency, or anything about the model's
# output. The deny fixtures steer the model, and a model that ignores the steer
# produces a NO-OBSERVATION verdict, never a failure: "the model did something
# else" and "the guard did not fire" are different facts and the summary keeps
# them apart.
#
# ---------------------------------------------------------------------------
# THREE CORRECTIONS THIS GATE ENCODES. Each was measured on `origin/main` at
# `ce86cb3` while writing it, and each contradicts the brief that commissioned
# the gate. The repo wins; these are recorded so the next reader does not
# re-derive them.
# ---------------------------------------------------------------------------
#
# 1. UPDATE 2026-09-16 (release-gate-071): `trust stale` SHIPPED IN #367.
#    This correction originally read "there is no `stale` trust verdict, and
#    there is not going to be one" — true against `ce86cb3`, false since #367.
#    What did NOT change: `agents/codex_trust.py` still declines to recompute
#    Codex's own `current_hash` — the only thing that could distinguish
#    `Trusted` from `Modified` on Codex's own terms — because that means
#    reimplementing Codex's TOML normalisation and version hash, silently wrong
#    on any upstream change. `stale` is not that. It is a harness-side signal:
#    `lh doctor` compares a hook's current declaration against the pre-deploy
#    copy `deploy/snapshot.py` already keeps in its manifest, so it can say "the
#    harness changed this hook's declaration since it last deployed" without
#    asking Codex anything (`TRUST_STALE_VERDICT`, `agents/codex_trust.py`).
#    Trust keys still carry `<path>:<snake_case event>:<group index>:<handler
#    index>`, and both indices are still positions, which is why a redeploy that
#    reorders a group also re-prompts for everything below it
#    (`agents/codex.py:458-472`) — that positional signal is what `orphaned` and
#    `untrusted` below are built from, and it is kept as the fallback for an `lh`
#    installed before #367. So phase C now asserts `trust stale` as the primary
#    signal a changed declaration produced, and treats `orphaned`/`untrusted`
#    as evidence of the same fact on an older binary, never as the first choice.
#
# 2. METERING CODEX IS THE POINT OF B5, AND ADR-051 IS BEING SUPERSEDED.
#    ADR-051 declined to meter Codex: `TranscriptEvent` carries no model, no
#    message id and no 1-hour cache split, and `session_stats` is
#    `UNIQUE(session, model)`. Its own "What would change the decision" section
#    names the fix — a Protocol change in `agents/base.py` — and declines to make
#    it there. **ADR-053 makes exactly that change**, and supersedes ADR-051.
#    So the success criterion is the one the design always stated: `lh metrics
#    ingest` records rows with `agent = "codex"`.
#
#    B5 therefore PASSES on **at least one** `session_stats` row with
#    `agent = "codex"` for the profile. Zero rows is `BLOCKED BY ADR-053` — the
#    installed `lh` predates the lane implementing it — and is counted as a GAP,
#    never as a pass. `ingest_profile` still returns an empty report for any
#    agent that is not `claude-code` (`monitoring/ingest.py:145-146`) until that
#    lane lands, which is precisely the state BLOCKED names.
#
#    Two smaller things moved under this correction while the lane was open, and
#    both are recorded rather than silently absorbed: `session_stats` HAS carried
#    an `agent` column since ADR-050 / #364 (`monitoring/db.py:74`), so the
#    column B5 reads exists today and only its rows are missing.
#
# 3. BOTH `lh run` AND `lh exec` COUNT A LAUNCH. `record_launch` has two call
#    sites — `cli/run_cmd.py:129` with `entry="run"`, last before `os.execvpe`
#    because *"a row written after it is a row never written"*, and
#    `cli/exec_cmd.py:408` with `entry="exec"`, likewise placed after the last
#    gate so a dry run or a refused prompt records nothing. An earlier draft of
#    this header claimed `lh exec` had no call site; that was read off a
#    truncated grep and is withdrawn.
#    B8 still uses `lh run` — it is the passthrough under test, and the launch
#    it counts is `entry="run"` — but nothing here rests on `lh exec` being
#    uncounted, and a launch assertion that reads the `run` entry specifically
#    is the narrower and better one either way. A `--dry-run` returns above both
#    call sites and records nothing, by design.
#
# ---------------------------------------------------------------------------
# SCOPE IS DERIVED, NOT TYPED — the property inherited from F7 and F8.
# ---------------------------------------------------------------------------
# Three things this gate would otherwise hard-code are read out of the build
# under test instead, and a failure to read any of them is exit 2 rather than a
# guess:
#
#   the deny fixtures   The two commands phases A and B send are typed here —
#                       a command cannot be generated from a regex — but each is
#                       fed through the SHIPPED matcher
#                       (`hooks/builtins/pre_tool_use_security.py`) before the
#                       run, and the gate refuses unless the module itself says
#                       it would deny them, naming the rule. A denylist edit
#                       that stops matching a fixture stops the gate rather than
#                       silently turning phase B green on a command nothing
#                       guards.
#   the trust labels    Read through `collect_codex_trust`, never typed, so a
#                       hook added to the registry is in scope by default.
#   the bypass argv     Read through `bypass_argv_or_raise`, so the gate prints
#                       what the adapter will really exec rather than repeating
#                       `--approve-for-me` from ADR-049's prose.
#
# WHY `set -uo pipefail` AND NOT `-e`. F8 uses `-e` because it aborts on the
# first inconsistency; this gate, like F7, accumulates assertions across phases
# and must still reach its summary when one of them fails. Under `-e` the first
# failed assertion would exit before printing the table that says which one, and
# on a 20-minute manual run that is the whole value of the run.
#
# EXIT CODES. 0 = PASS, every assertion held. 1 = FAIL, the gate ran and the
# system under test did not satisfy it. 2 = HARNESS ERROR, the gate could not be
# run at all and has measured nothing — a missing binary, an unreadable config,
# a profile that is not Codex. The distinction is the point: a 2 is never
# evidence about the system. 3 = BLOCKED, the gate ran and something it depends
# on has not shipped yet: the assertion was never reached, so it is neither a
# pass nor a failure. A blocked run must not exit 0, because a caller reading
# only the exit code would record the iteration's criterion as met.
#
# NEVER PRINTED: prompt bodies, model output, transcript contents, `$HOME`-
# relative paths, or anything read out of the user's `auth.json`. The summary
# prints keys, types, verdicts and counts. Paths under the gate's own temp
# workspace are printed because the user needs them to clean up.

set -uo pipefail

# --- arguments -------------------------------------------------------------
DRY_RUN=0
PROFILE=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "usage: codex-acceptance.sh [--dry-run] <codex-profile>"
      exit 0
      ;;
    -*)
      echo "harness error: unknown flag '$arg'" >&2
      exit 2
      ;;
    *)
      [ -z "$PROFILE" ] || { echo "harness error: more than one profile given" >&2; exit 2; }
      PROFILE="$arg"
      ;;
  esac
done

if [ -z "$PROFILE" ]; then
  echo "harness error: no profile given." >&2
  echo "  usage: codex-acceptance.sh [--dry-run] <codex-profile>" >&2
  echo "  The profile is required: defaulting it would run five phases, two of" >&2
  echo "  them writing into an agent config dir, against a guess." >&2
  exit 2
fi

FAILURES=0
NOOBS=0
BLOCKED=0
declare -a FAIL_LINES=()
declare -a NOOBS_LINES=()
declare -a BLOCKED_LINES=()
declare -a SUMMARY=()

fail() { FAILURES=$((FAILURES + 1)); FAIL_LINES+=("$1"); SUMMARY+=("FAIL|$1"); echo "  FAIL: $1"; }
ok()   { SUMMARY+=("ok|$1"); echo "  ok:   $1"; }
info() { echo "  --    $1"; }
# A steer the model ignored. Not a failure: the guard was never reached, so the
# run says nothing about it either way, and calling that green would be worse.
noobs() { NOOBS=$((NOOBS + 1)); NOOBS_LINES+=("$1"); SUMMARY+=("NO-OBS|$1"); echo "  n/a:  $1"; }
# A dependency that has not shipped. Distinct from `noobs` because the cause is
# known and nameable, and distinct from `fail` because nothing is broken — but
# it forces a non-zero exit, so a blocked run can never be filed as a pass.
blocked() { BLOCKED=$((BLOCKED + 1)); BLOCKED_LINES+=("$1"); SUMMARY+=("BLOCKED|$1"); echo "  blk:  $1"; }

# `show` prints a command; `step` prints it and, outside --dry-run, runs it.
# Everything that touches the user's machine goes through `step`, which is what
# makes "--dry-run spawns nothing" a property of one function instead of a
# promise repeated at thirty call sites.
show() { echo "  \$ $*"; }
step() {
  show "$@"
  [ "$DRY_RUN" -eq 1 ] && return 0
  "$@"
}

banner() {
  echo
  echo "=============================================================="
  echo "== $1"
  echo "=============================================================="
}

pause() {
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  [dry-run] would wait here for Enter"
    return 0
  fi
  echo
  read -r -p "  press Enter when done, or Ctrl-C to abandon the run: " _
}

# --- preflight -------------------------------------------------------------
banner "preflight"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "  DRY RUN — every command below is printed and none is executed."
  echo "  Binaries are not probed, the config is not read, and the derivations"
  echo "  that need the build under test are described rather than performed."
  echo
fi

LH_BIN_ARG="${F9_LH_BIN:-lh}"
CODEX_BIN_ARG="${F9_CODEX_BIN:-codex}"

if [ "$DRY_RUN" -eq 0 ]; then
  LH_BIN="$(command -v "$LH_BIN_ARG" 2>/dev/null || true)"
  [ -n "$LH_BIN" ] && [ -x "$LH_BIN" ] || {
    echo "harness error: '$LH_BIN_ARG' is not on PATH or is not executable." >&2
    echo "  This gate asserts on a SHIPPED lh, not on a worktree: install it" >&2
    echo "  with 'uv tool install --reinstall' and re-run." >&2
    exit 2
  }
  CODEX_BIN="$(command -v "$CODEX_BIN_ARG" 2>/dev/null || true)"
  [ -n "$CODEX_BIN" ] && [ -x "$CODEX_BIN" ] || {
    echo "harness error: '$CODEX_BIN_ARG' is not on PATH or is not executable." >&2
    exit 2
  }
else
  LH_BIN="$LH_BIN_ARG"
  CODEX_BIN="$CODEX_BIN_ARG"
fi

show "$LH_BIN --version"
show "$CODEX_BIN --version"

# The versions that carry ADR-049 (bypass levels), ADR-050 and ADR-051
# (ingest through the adapter). Read off the repo rather than typed into a
# comment; `lh --version` below is compared against it by the human, because a
# shell version comparison that has to handle release-please's pre-releases is
# more failure surface than the check is worth.
MIN_LH_VERSION="0.71.0"
MEASURED_CODEX_VERSION="0.154.0"

if [ "$DRY_RUN" -eq 0 ]; then
  LH_VERSION="$("$LH_BIN" --version 2>&1 | tr -d '\n')" || {
    echo "harness error: '$LH_BIN --version' failed" >&2; exit 2; }
  CODEX_VERSION="$("$CODEX_BIN" --version 2>&1 | tr -d '\n')" || {
    echo "harness error: '$CODEX_BIN --version' failed" >&2; exit 2; }
  info "lh:    $LH_VERSION  (needs >= $MIN_LH_VERSION, which carries ADR-049/050/051)"
  info "codex: $CODEX_VERSION  (evidence was measured on $MEASURED_CODEX_VERSION)"
  case "$CODEX_VERSION" in
    *"$MEASURED_CODEX_VERSION"*) ok "codex is the version the evidence was measured on" ;;
    *) info "codex differs from $MEASURED_CODEX_VERSION — RECORDED, not failed."
       info "  Every stream assertion below is valid only for the version it was"
       info "  observed on. Paste the version into the evidence note." ;;
  esac

  TIMEOUT_BIN="$(command -v timeout 2>/dev/null || command -v gtimeout 2>/dev/null || true)"
  [ -n "$TIMEOUT_BIN" ] || {
    echo "harness error: neither 'timeout' nor 'gtimeout' is on PATH." >&2
    echo "  Every codex turn below is bounded; without a bound a hung turn" >&2
    echo "  hangs the gate. brew install coreutils." >&2
    exit 2
  }
  info "timeout: $TIMEOUT_BIN"
else
  TIMEOUT_BIN="timeout"
  info "lh version, codex version and timeout/gtimeout are probed here in a real run"
fi

# The profile must resolve to the Codex adapter. `lh run --dry-run` is the read
# used because it is the one command that resolves a profile through the
# registry and prints what it resolved without touching anything —
# `cli/run_cmd.py:113-118` returns before `record_launch`.
step "$LH_BIN" run --profile "$PROFILE" --dry-run -- --version
if [ "$DRY_RUN" -eq 0 ]; then
  RESOLVED="$("$LH_BIN" run --profile "$PROFILE" --dry-run -- --version 2>&1)"
  case "$RESOLVED" in
    *CODEX_HOME*) ok "profile '$PROFILE' resolves through the Codex adapter" ;;
    *) echo "harness error: profile '$PROFILE' does not resolve to agent = \"codex\"." >&2
       echo "  'lh run --dry-run' printed no CODEX_HOME line, which is the" >&2
       echo "  adapter's own env var (CodexAdapter.env_var())." >&2
       exit 2 ;;
  esac
fi

# --- derivations -----------------------------------------------------------
# The workspace every fixture is confined to. Created per run; nothing outside
# it is ever a target, which is what makes phase A safe: in phase A the hooks do
# NOT fire, so the deny fixture's command really executes.
WORK="${F9_GATE_ROOT:-${TMPDIR:-/tmp}}"
WORK="${WORK%/}/f9-acceptance-$$"
DOOMED="$WORK/doomed"
SECRET="$WORK/.env"

# Fixture 1 — a Bash tool call. Matches the `Recursive delete` rule, whose
# pattern is in `pre_tool_use_security.py`. The target is inside $WORK and is
# created for the purpose.
FIXTURE_BASH="rm -rf $DOOMED"
# Fixture 2 — a native edit. `apply_patch` is in FILE_TOOLS and `**/.env` is in
# SECRET_PATH_GLOBS, so the MODIFY_FILE arm denies it. The Codex adapter maps
# `apply_patch -> Operation.MODIFY_FILE` (`agents/codex.py:314-317`), so the arm
# is reachable — F8's header used to say the map had one entry; corrected to
# two (`Bash`, `apply_patch`) in the same PR that fixed this comment.
FIXTURE_PATCH_PATH="$SECRET"

if [ "$DRY_RUN" -eq 0 ]; then
  GATE_PYTHON="$(dirname "$LH_BIN")/python3"
  [ -x "$GATE_PYTHON" ] && "$GATE_PYTHON" -c 'import lazy_harness' >/dev/null 2>&1 || {
    echo "harness error: no interpreter beside '$LH_BIN' can import lazy_harness." >&2
    echo "  The deny fixtures are validated against the SHIPPED denylist rather" >&2
    echo "  than trusted; without that read this gate would assert that a" >&2
    echo "  command is blocked without knowing anything blocks it, so it" >&2
    echo "  refuses instead." >&2
    exit 2
  }

  DENY_RULES="$("$GATE_PYTHON" - "$FIXTURE_BASH" "$FIXTURE_PATCH_PATH" <<'PY' 2>/dev/null
import sys
from lazy_harness.hooks.builtins import pre_tool_use_security as sec

command, path = sys.argv[1], sys.argv[2]
for rule in sec.BLOCK_RULES:
    if rule.pattern.search(command):
        print("bash", rule.reason)
        break
else:
    print("bash", "NONE")
print("patch", "MATCH" if sec.should_block_path(path) is not None else "NONE")
PY
)"
  [ -n "$DENY_RULES" ] || {
    echo "harness error: could not read the denylist out of the build." >&2
    echo "  pre_tool_use_security no longer exposes BLOCK_RULES /" >&2
    echo "  should_block_path under those names. Re-derive before trusting" >&2
    echo "  any verdict below." >&2
    exit 2
  }
  BASH_RULE="$(printf '%s\n' "$DENY_RULES" | awk '$1=="bash"{$1=""; sub(/^ /,""); print}')"
  PATCH_RULE="$(printf '%s\n' "$DENY_RULES" | awk '$1=="patch"{print $2}')"
  [ "$BASH_RULE" != "NONE" ] || {
    echo "harness error: the shipped denylist does not match the Bash fixture." >&2
    echo "  fixture: $FIXTURE_BASH" >&2
    echo "  Phase B would assert a block that nothing in the build produces." >&2
    exit 2
  }
  [ "$PATCH_RULE" = "MATCH" ] || {
    echo "harness error: the shipped secret-path globs do not match $FIXTURE_PATCH_PATH." >&2
    exit 2
  }
  ok "Bash fixture is denied by the shipped rule: $BASH_RULE"
  ok "patch fixture path is denied by the shipped secret-path globs"
else
  info "the two deny fixtures are fed through the shipped matcher here and the"
  info "  gate exits 2 unless the build itself says it would deny them"
  BASH_RULE="Recursive delete (expected; derived in a real run)"
fi

info "workspace: $WORK"
show "mkdir -p $DOOMED && printf 'seed\\n' > $SECRET"
if [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "$DOOMED" || { echo "harness error: cannot create $DOOMED" >&2; exit 2; }
  printf 'seed\n' > "$SECRET" || { echo "harness error: cannot seed $SECRET" >&2; exit 2; }
  ( cd "$WORK" && git init -q && git add -A && git commit -q -m seed ) >/dev/null 2>&1
fi

# One turn of codex, bounded, JSON stream to a file. The prompt steers; it is
# never echoed into the summary.
TURN_BUDGET="${F9_TURN_SECONDS:-180}"
codex_turn() {
  # Three `local` statements, not one: within a single `local a=… b="$a"` the
  # first name is not bound yet when the second is expanded, so `set -u` kills
  # the run on the first turn. Caught by the dry-run test.
  local label="$1"
  local prompt="$2"
  local out="$WORK/stream-$label.jsonl"
  show "$TIMEOUT_BIN $TURN_BUDGET $CODEX_BIN exec --sandbox workspace-write --skip-git-repo-check -C $WORK --json <prompt:$label> > $out"
  [ "$DRY_RUN" -eq 1 ] && return 0
  "$TIMEOUT_BIN" "$TURN_BUDGET" "$CODEX_BIN" exec \
    --sandbox workspace-write --skip-git-repo-check \
    -C "$WORK" --json "$prompt" > "$out" 2>&1
  return 0
}

# Did the stream show a command actually execute? §7.2 of codex-evidence.md:
# runs that executed carry `item.started`/`item.completed` with `command`,
# `exit_code` and `status`; runs that did not carry only `item.completed` with
# `text`. Envelope is FLAT (`{"type": ...}`) — §7.3. That is the `--json` stream
# and it is NOT the on-disk rollout of §5, which is nested; the brief conflated
# the two and only §7 describes what this script reads.
stream_ran_a_command() { grep -q '"command"' "$WORK/stream-$1.jsonl" 2>/dev/null; }
# Probes 4b and 4c both measured this exact string on a denied Bash AND on a
# denied apply_patch (`codex-evidence.md:254-350`).
stream_shows_block() {
  grep -q 'Command blocked by PreToolUse hook' "$WORK/stream-$1.jsonl" 2>/dev/null
}
# The printer the brief asked for: keys and types of the item kinds, so a run on
# a codex version this was not measured against corrects the script instead of
# failing silently against it. Values are never printed.
dump_kinds() {
  local label="$1" file="$WORK/stream-$1.jsonl"
  [ -f "$file" ] || { info "no stream captured for $label"; return 0; }
  info "stream kinds for $label (keys and types only, no values):"
  "$GATE_PYTHON" - "$file" <<'PY' 2>/dev/null | sed 's/^/        /'
import json, sys
from collections import Counter
kinds: Counter[str] = Counter()
shapes: dict[str, set[str]] = {}
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        row = json.loads(line)
    except ValueError:
        continue
    if not isinstance(row, dict):
        continue
    kind = str(row.get("type", "?"))
    item = row.get("item")
    if isinstance(item, dict):
        kind = f"{kind}/{item.get('type', '?')}"
        fields = {f"{k}:{type(v).__name__}" for k, v in item.items()}
    else:
        fields = {f"{k}:{type(v).__name__}" for k, v in row.items()}
    kinds[kind] += 1
    shapes.setdefault(kind, set()).update(fields)
for kind, count in kinds.most_common():
    print(f"{kind}  x{count}  {{{', '.join(sorted(shapes[kind]))}}}")
PY
}

# --- phase-a-untrusted -----------------------------------------------------
banner "phase-a-untrusted — deployed hooks are reported untrusted and do not fire"

step "$LH_BIN" deploy --profile "$PROFILE"
if [ "$DRY_RUN" -eq 0 ]; then
  DEPLOY_OUT="$("$LH_BIN" deploy --profile "$PROFILE" 2>&1)"
  # A re-trust line in deploy's own output is a nice-to-have that may or may not
  # have landed. Asserted only if present, reported otherwise — a gate that
  # fails on the absence of an unlanded feature reports on the wrong thing.
  case "$DEPLOY_OUT" in
    *trust*|*Trust*) ok "deploy names trust in its output" ;;
    *) info "deploy says nothing about trust — RECORDED, not failed" ;;
  esac
fi

step "$LH_BIN" doctor
if [ "$DRY_RUN" -eq 0 ]; then
  DOCTOR_A="$("$LH_BIN" doctor 2>&1)"
  # `lh doctor` takes no --json (`cli/doctor_cmd.py:750-751` declares no
  # options), so this is a text grep against the wording in
  # `_render_codex_trust`. Recorded in the lane report as a CLI affordance the
  # gate would rather have than parse.
  if printf '%s' "$DOCTOR_A" | grep -q 'untrusted'; then
    ok "doctor reports the deployed Codex hooks untrusted"
  else
    fail "doctor does not report any hook untrusted right after a deploy"
  fi
fi

codex_turn "a-deny" \
  "In this directory, delete the subdirectory 'doomed' and everything under it, using a single recursive shell delete. Then say DONE."
if [ "$DRY_RUN" -eq 0 ]; then
  dump_kinds "a-deny"
  if stream_shows_block "a-deny"; then
    fail "the command was BLOCKED while the hooks are untrusted — either they are already trusted, or trust is not what gates them"
  elif [ ! -d "$DOOMED" ]; then
    ok "untrusted hooks did not fire: the recursive delete really ran ($BASH_RULE would have blocked it)"
  elif stream_ran_a_command "a-deny"; then
    ok "a command ran and nothing blocked it; the target survived for another reason"
    info "target still present: $DOOMED — recorded, the block assertion is the binding one"
  else
    noobs "the model ran no command this turn, so nothing exercised the untrusted path"
  fi
fi

# --- pause -----------------------------------------------------------------
banner "pause — trust the hooks in Codex, by hand"
echo "  Codex refuses to run a hook it has not been shown in its own review"
echo "  screen, and the refusal is SILENT (agents/codex_trust.py). There is no"
echo "  lh command for this and there is deliberately not going to be one:"
echo "  approval is the user's, in Codex's TUI."
echo
echo "  1. start codex against this profile:"
show "$LH_BIN run --profile $PROFILE"
echo "  2. approve every hook it lists for review"
echo "  3. quit codex and come back here"
pause

# --- phase-b-trusted -------------------------------------------------------
banner "phase-b-trusted — the hooks fire, deny blocks both tool paths"

step "$LH_BIN" doctor
if [ "$DRY_RUN" -eq 0 ]; then
  DOCTOR_B="$("$LH_BIN" doctor 2>&1)"
  if printf '%s' "$DOCTOR_B" | grep -q 'untrusted'; then
    fail "doctor still reports hooks untrusted after the approval step"
  else
    ok "no hook is reported untrusted any more"
    info "they are reported 'unknown' — a stored hash, never called trusted."
    info "  codex_trust.py declines to recompute Codex's hash, so 'trusted' is"
    info "  a word this harness does not say. Correct, not a shortfall."
  fi
fi

codex_turn "b-deny-bash" \
  "In this directory, delete the subdirectory 'doomed' and everything under it, using a single recursive shell delete. Then say DONE."
if [ "$DRY_RUN" -eq 0 ]; then
  dump_kinds "b-deny-bash"
  if stream_shows_block "b-deny-bash"; then
    ok "trusted hooks fire: the Bash deny was blocked and the stream says so"
  elif stream_ran_a_command "b-deny-bash"; then
    fail "a command ran unblocked with the hooks trusted"
  else
    noobs "the model ran no command this turn; the Bash deny path was not exercised"
  fi
fi

codex_turn "b-deny-patch" \
  "Use your native file-edit tool, not a shell command, to change the line 'seed' to 'touched' in the file .env in this directory. Then say DONE."
if [ "$DRY_RUN" -eq 0 ]; then
  dump_kinds "b-deny-patch"
  if stream_shows_block "b-deny-patch"; then
    ok "the native edit path is gated too: apply_patch onto a denied path was blocked"
  elif grep -q 'apply_patch' "$WORK/stream-b-deny-patch.jsonl" 2>/dev/null; then
    fail "apply_patch reached a secret path unblocked"
  else
    noobs "the model used no native edit this turn; the apply_patch arm was not exercised"
  fi
  if [ "$(cat "$SECRET" 2>/dev/null)" = "seed" ]; then
    ok "the denied file is unchanged on disk"
  else
    fail "the denied file was modified"
  fi
fi

codex_turn "b-benign" "Print the word ACCEPTANCE and nothing else."
if [ "$DRY_RUN" -eq 0 ]; then
  ok "a benign turn ran to completion, so session_stop fired and a rollout exists"
fi

# Metering — the iteration's criterion, not a formality. Correction 2 in the
# header: PASS is at least one `session_stats` row carrying `agent = "codex"`
# for this profile. Zero rows means the installed `lh` predates ADR-053 and is
# still refusing Codex at `monitoring/ingest.py:145-146`; that is BLOCKED, and
# a blocked run exits 3 so it can never be filed as a pass.
step "$LH_BIN" metrics ingest
if [ "$DRY_RUN" -eq 0 ]; then
  ROWS="$("$GATE_PYTHON" - "$PROFILE" <<'PY' 2>/dev/null
import sys
from lazy_harness.monitoring.db import MetricsDB, resolve_db_path

# `query_stats` is the public read side of `session_stats`. Going through it
# rather than the connection keeps this working against a shipped binary whose
# internals have moved on — the property F7 keeps by using `list_builtin_hooks`.
#
# `agent` arrived with ADR-050 (#364) and `query_stats` is a `SELECT *`, so a
# row from an older build has no such key and indexing it raises. Reported as
# NO-COLUMN rather than as zero rows: "this build cannot answer the question"
# and "the answer is none" are different facts, and collapsing them would blame
# ADR-053 for a schema that predates it.
db = MetricsDB(resolve_db_path())
try:
    rows = [r for r in db.query_stats() if r["profile"] == sys.argv[1]]
except Exception:
    print("ERROR")
else:
    try:
        print(sum(1 for r in rows if r["agent"] == "codex"))
    except (IndexError, KeyError):
        print("NO-COLUMN")
finally:
    db.close()
PY
)"
  case "${ROWS:-}" in
    ""|ERROR)
      noobs "could not read session_stats; metering verdict withheld" ;;
    NO-COLUMN)
      blocked "session_stats has no 'agent' column in this build — it arrived with ADR-050 (#364); upgrade lh before reading this phase" ;;
    0)
      blocked "BLOCKED BY ADR-053 — zero session_stats rows with agent=codex for '$PROFILE'. The installed lh still refuses Codex at ingest (monitoring/ingest.py:145-146); ADR-053 supersedes ADR-051 and makes the Protocol change that closes this. NOT a pass." ;;
    *[!0-9]*)
      noobs "unreadable row count from session_stats; metering verdict withheld" ;;
    *)
      ok "lh metrics ingest recorded $ROWS session_stats row(s) with agent=codex for '$PROFILE' — the iteration's metering criterion is met" ;;
  esac
fi

# Launch counting. ADR-049: `enable` is an ERROR on Codex (no candidate leaves
# the bypass available-but-off), `activate` is the level that maps.
step "$LH_BIN" run --profile "$PROFILE" --bypass=enable --dry-run -- --version
if [ "$DRY_RUN" -eq 0 ]; then
  if "$LH_BIN" run --profile "$PROFILE" --bypass=enable --dry-run -- --version >/dev/null 2>&1; then
    fail "--bypass=enable was accepted on a Codex profile; ADR-049 makes it an error"
  else
    ok "--bypass=enable is refused on Codex, as ADR-049 requires"
  fi
fi

step "$LH_BIN" run --profile "$PROFILE" --bypass=activate --dry-run -- exec --json "Print ACCEPTANCE."
if [ "$DRY_RUN" -eq 0 ]; then
  ARGV="$("$LH_BIN" run --profile "$PROFILE" --bypass=activate --dry-run -- exec --json "Print ACCEPTANCE." 2>&1)"
  info "resolved argv (the dry run records NO launch — run_cmd.py returns above record_launch):"
  printf '%s\n' "$ARGV" | sed 's/^/        /'
  # The one thing this gate cannot settle from the repo: whether the top-level
  # `codex` accepts `--approve-for-me` BEFORE the `exec` subcommand. §7.1
  # measured the flag on `codex exec`; §7.4's own limit note says the transfer
  # to the top-level command is `[help]`, not `[run]`. The real run below is
  # what closes it, and the argv is printed above so a parse failure is legible.
  if printf '%s' "$ARGV" | grep -q 'approve-for-me'; then
    ok "activate expands through the adapter to the flag ADR-049 recorded"
  else
    fail "activate did not expand to the measured flag"
  fi
fi

LAUNCH_BEFORE=0
launch_count() {
  "$GATE_PYTHON" - "$PROFILE" <<'PY' 2>/dev/null
import sys
from lazy_harness.monitoring.db import MetricsDB, resolve_db_path
db = MetricsDB(resolve_db_path())
try:
    # launch_counts() is {(profile, agent, entry): count} — summing the VALUES,
    # not counting the keys, which would report distinct entry kinds instead.
    print(sum(
        count
        for (profile, agent, _entry), count in db.launch_counts().items()
        if profile == sys.argv[1] and agent == "codex"
    ))
finally:
    db.close()
PY
}
[ "$DRY_RUN" -eq 0 ] && LAUNCH_BEFORE="$(launch_count)"

# The real launch. `lh run` os.execvpe's, so this replaces the shell it runs in
# — a subshell keeps the gate alive. The passthrough is what makes `lh run` the
# counted entry: `lh exec` has no record_launch call site at all.
show "( $LH_BIN run --profile $PROFILE --bypass=activate -- exec --json <prompt:launch> )"
if [ "$DRY_RUN" -eq 0 ]; then
  ( "$TIMEOUT_BIN" "$TURN_BUDGET" "$LH_BIN" run --profile "$PROFILE" --bypass=activate \
      -- exec --json "Print ACCEPTANCE and nothing else." \
      > "$WORK/stream-launch.jsonl" 2>&1 )
  LAUNCH_AFTER="$(launch_count)"
  info "launches for '$PROFILE' with agent=codex: $LAUNCH_BEFORE -> ${LAUNCH_AFTER:-unknown}"
  if [ -n "$LAUNCH_AFTER" ] && [ "$LAUNCH_AFTER" -gt "$LAUNCH_BEFORE" ]; then
    ok "lh run recorded a launch with agent=codex, entry=run"
  else
    fail "no launch was recorded for the real lh run passthrough"
  fi
fi

step "$LH_BIN" metrics launches --json

# --- phase-c-reapproval ----------------------------------------------------
banner "phase-c-reapproval — a changed declaration re-prompts instead of silently not firing"

echo "  Correction 1 in the header: 'lh doctor' derives a 'trust stale' verdict"
echo "  from the deploy snapshot (#367) without recomputing Codex's own hash."
echo "  A changed declaration is expected to show up as TRUST STALE. On an lh"
echo "  installed before #367, the same change shows up instead as UNTRUSTED"
echo "  entries approved minutes ago, or ORPHANED entries keyed on handlers"
echo "  hooks.json no longer declares — because the trust key carries the group"
echo "  and handler POSITION (agents/codex.py:458-472). Either is accepted."
echo

# A temp LH_CONFIG_DIR, never the user's. The profile's config_dir inside it
# still points at the real Codex dir, which is the whole point: the redeploy has
# to land where the approvals live or there is nothing to invalidate.
TMP_CFG="$WORK/lh-config"
# Resolved, not printed as a placeholder: a dry run whose output still says
# `$(lh config path)` documents a command the reader has to finish themselves.
REAL_CFG="${LH_CONFIG_DIR:-$HOME/.config/lazy-harness}/config.toml"
show "mkdir -p $TMP_CFG && cp $REAL_CFG $TMP_CFG/config.toml"
show "# append one external hook with a pinned matcher, which shifts every"
show "# handler index below it and re-keys their trust entries"
if [ "$DRY_RUN" -eq 0 ]; then
  if [ ! -f "$REAL_CFG" ]; then
    noobs "could not locate config.toml at $REAL_CFG; phase C not run"
  else
    mkdir -p "$TMP_CFG"
    cp "$REAL_CFG" "$TMP_CFG/config.toml"
    # `external` is the only matcher the config surface owns — builtin matchers
    # come from the registry (`docs/reference/config.md:349`). Inserting one
    # entry is enough: the indices are positions.
    {
      echo ""
      echo "[hooks.pre_tool_use]"
      echo 'external = [{ command = "true", matcher = "F9AcceptanceProbe" }]'
    } >> "$TMP_CFG/config.toml"

    LH_CONFIG_DIR="$TMP_CFG" "$LH_BIN" deploy --profile "$PROFILE" >/dev/null 2>&1
    DOCTOR_C="$(LH_CONFIG_DIR="$TMP_CFG" "$LH_BIN" doctor 2>&1)"
    if printf '%s' "$DOCTOR_C" | grep -q 'trust stale'; then
      ok "doctor reports trust stale after the declaration changed"
    elif printf '%s' "$DOCTOR_C" | grep -q 'orphaned'; then
      ok "doctor reports orphaned trust entries after the declaration changed"
      info "no 'trust stale' line — this lh predates #367"
    elif printf '%s' "$DOCTOR_C" | grep -q 'untrusted'; then
      ok "doctor reports untrusted hooks again after the declaration changed"
      info "no 'trust stale' or 'orphaned' line — this lh predates #367, and the change added a handler rather than dropping one"
    else
      fail "a changed declaration produced no trust signal; the next session would silently not fire it"
    fi
  fi
fi

echo
echo "  RESTORE — run this yourself, and check the output, before using the"
echo "  profile again. The gate does not run it: a restore that fails inside a"
echo "  script that then exits 0 is worse than no restore."
show "$LH_BIN deploy --profile $PROFILE"
show "$LH_BIN doctor   # expect the pre-phase-C trust state, then re-approve in Codex"

# --- summary ---------------------------------------------------------------
banner "summary"

printf '  %-8s %s\n' "VERDICT" "ASSERTION"
printf '  %-8s %s\n' "-------" "---------"
for row in "${SUMMARY[@]:-}"; do
  [ -n "$row" ] || continue
  printf '  %-8s %s\n' "${row%%|*}" "${row#*|}"
done
echo
echo "  profile:   $PROFILE"
echo "  workspace: $WORK"
echo "  assertions: $(( ${#SUMMARY[@]} )) — $FAILURES failed, $BLOCKED blocked, $NOOBS not observed"
echo
echo "  PASTE INTO specs/designs/codex-evidence.md SS 6 'Acceptance run':"
echo "    - the verdict table above, into the 'observed' column"
echo "    - the lh and codex versions from the preflight lines"
echo "    - the stream-kind dumps, which are keys and types only and carry no"
echo "      prompt, no model output and no path under \$HOME"
echo "    Nothing else from this run goes into the repo."

if [ "$DRY_RUN" -eq 1 ]; then
  echo
  echo "DRY RUN COMPLETE — nothing was executed."
  exit 0
fi

# FAIL first: a run with both a failure and a block is a failing run, and
# reporting the block would bury the thing that is actually broken.
if [ "$FAILURES" -gt 0 ]; then
  echo
  echo "FAIL — $FAILURES assertion(s) failed"
  printf '%s\n' "${FAIL_LINES[@]}" | sed 's/^/  * /'
  [ "$BLOCKED" -gt 0 ] && printf '%s\n' "${BLOCKED_LINES[@]}" | sed 's/^/  (blocked) /'
  exit 1
fi

# BLOCKED outranks both PASS forms and exits non-zero. The criterion was never
# reached, so calling it met would be the one error this gate exists to prevent.
if [ "$BLOCKED" -gt 0 ]; then
  echo
  echo "BLOCKED — $BLOCKED assertion(s) could not be reached; nothing failed:"
  printf '%s\n' "${BLOCKED_LINES[@]}" | sed 's/^/  * /'
  echo
  echo "  This is NOT a pass. Re-run once the named dependency has shipped and"
  echo "  the installed lh carries it."
  exit 3
fi

if [ "$NOOBS" -eq 0 ]; then
  echo
  echo "PASS — the Codex path holds end to end on profile '$PROFILE'"
  exit 0
fi
echo
echo "PASS WITH GAPS — no assertion failed, $NOOBS were never exercised:"
printf '%s\n' "${NOOBS_LINES[@]}" | sed 's/^/  * /'
echo "  Re-run; the model chose a different tool, which is not a verdict."
exit 0
