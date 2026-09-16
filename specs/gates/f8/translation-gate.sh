#!/usr/bin/env bash
# F8 translation gate — which builtins go INERT when the same tool call is
# parsed by the Codex adapter instead of the Claude Code one?
#
# That is the whole question, and it is the ONLY question. F7
# (`../f7/isolation-gate.sh`) asks whether a hook writes its evidence under the
# invoking profile's config dir, and says so in its own header: *"WHAT THIS GATE
# DELIBERATELY DOES NOT MEASURE: the translation itself."* This is that second
# gate. The two are siblings and neither subsumes the other — a hook can be
# perfectly isolated and still see nothing.
#
# INERT IS NOT ABSENT, AND THE DIFFERENCE IS THE POINT.
# `hooks/signal_gaps.py` omits `session-export` and `stop-context-rotate` under
# Codex and `lh deploy` NAMES each omission in its own output. That is a declared,
# visible gap and it is not what this gate is for. An inert builtin is the
# opposite: it deploys, it is wired, it runs, it exits 0, and it enforces nothing,
# because the `ToolCall` it was handed came back with the field it gates on
# emptied. Green because it cannot fail. Nothing in the deploy output, the
# registry or the config says so.
#
# ---------------------------------------------------------------------------
# SCOPE IS DERIVED, NOT TYPED — the property inherited from F7.
# ---------------------------------------------------------------------------
# The asserted set is every name `list_builtin_hooks()` returns. It is split by
# `BuiltinHookSpec.operations`, which is the registry's own answer to "does this
# hook look at tool calls": *"Empty means a hook that does not look at tool calls
# at all."*
#
#   NO_TOOL  operations == frozenset(). Cannot be made inert by a translation it
#            never reads. Accounted for, never fed.
#   TOOL     operations non-empty. Fed one payload PER DECLARED OPERATION.
#
# `operations` has no public reader, so it comes off `_BUILTIN_HOOKS` directly.
# That is the one private read in this script, for the same reason F7 makes it
# and `tests/unit/test_hook_matcher_coverage.py:82` makes it: if that dict moves,
# the registry query returns nothing and this gate exits 2 rather than guessing.
#
# WHY PER OPERATION AND NOT PER HOOK. Six of the seven tool-reading builtins
# declare exactly one operation, so for them the two are the same thing. Only
# `pre-tool-use-security` declares three, and feeding it one payload would need a
# tiebreak — "which operation represents this hook" — that has no answer in the
# registry and would have to be typed here. Per-operation makes the verdict
# derivable instead:
#
#   INERT  every declared operation degrades. The hook has no reachable branch.
#   LIVE   at least one declared operation survives. It can still do work.
#
# That resolves `pre-tool-use-security` correctly and without a rule invented for
# it: its `run_command` arm survives (Codex maps `Bash`), so it is LIVE — while
# its `read_file` and `modify_file` arms degrade. A guard live on one half of its
# denylist and silent on the other is a real and separate problem; it is RECORDED
# at the end of this run and deliberately NOT asserted, because "half-inert" is a
# second question and two questions behind one exit code cannot say which broke.
#
# ---------------------------------------------------------------------------
# WHY A MAPPING FIX IS NOT A FIX — and the correction this gate produced.
# ---------------------------------------------------------------------------
# The prevailing account, in `specs/backlog.md` and in the brief that
# commissioned this gate, is that the five inert builtins fail by TWO mechanisms:
# `post-tool-use-format` and `pre-tool-use-read-size` at the `operation` gate,
# the other three one step lower at `tool.edits`. That account is right about
# where each hook returns FIRST and wrong about what follows from it.
#
# Measured 2026-09-16 by running the hooks, not by reading them:
#
#   post_tool_use_format.main(), operation=MODIFY_FILE, edits=()
#     -> target file unchanged, 'x   =    1\n'
#   post_tool_use_format.main(), operation=MODIFY_FILE, edits=(FileEdit(py),)
#     -> target file formatted,  'x = 1\n'
#
#   pre_tool_use_read_size.main(), operation=READ_FILE, reads=()
#     -> system_message ''
#   pre_tool_use_read_size.main(), operation=READ_FILE, reads=(big,)
#     -> system_message 'WARN: ... is 5000 lines (~6250 tokens) ...'
#
# The operation gate is the first of TWO gates in those two hooks, not the only
# one: `post_tool_use_format.py:36` iterates `tool.edits` and
# `pre_tool_use_read_size.py:119` iterates `tool.reads`, both downstream of the
# gate that opens. So ALL FIVE need the structure, and widening
# `CodexAdapter._TOOL_OPERATIONS` (`agents/codex.py:92`) revives NONE of them.
#
# `fake-translate-operations-only.sh` is that change, emulated. It was written
# expecting this gate to fail it and it PASSES — nothing left the inert set —
# which is a stronger result than the one it was built to get: the mapping fix is
# not a partial fix, it is a no-op, and it hands whoever ships it a green gate
# that is green for exactly the reason it was green before.
#
# ---------------------------------------------------------------------------
# WHAT THIS GATE DOES NOT MEASURE — read this before trusting a green run.
# ---------------------------------------------------------------------------
# Both sides of every comparison are PYTHON OBJECTS: the shipped
# `ClaudeCodeAdapter` and the shipped `CodexAdapter`. The `codex` binary is never
# invoked, and the payloads are written in Claude Code's dialect.
#
# That is sound for the question asked — "which builtins go inert across the
# shipped adapter pair" is fully determined by those two objects — and it is NOT
# sound for the question it sits next to: what Codex's real wire dialect is for an
# edit. `CodexAdapter.parse_hook_input` records that dialect as OBSERVED
# (`codex.py:148-152`, snake_case keys, `tool_name`/`tool_input`), which is why
# the payloads below are written the way they are. The live-binary probe named as
# a precondition in `specs/backlog.md` was ATTEMPTED on 2026-09-16 against
# `codex-cli 0.154.0` with a disposable `CODEX_HOME` and a payload-dumping
# `hooks.json`, and was refused by the session's own tool policy before `codex
# exec` ran. It has not been performed. Until it is, a green run here says the
# adapter pair agrees with this file's expectations, and says nothing whatever
# about the binary.
#
# ---------------------------------------------------------------------------
# USAGE
# ---------------------------------------------------------------------------
#   ./translation-gate.sh [translator]
#
# `translator` defaults to `./real-translate.sh` and is the ONE injection point,
# taking the place F7 gives the `lh` binary. It is invoked once, reads TSV
# records on stdin and writes TSV records on stdout; the protocol is documented
# in `translate.py`. The controls are shims over the same file:
#
#   real-translate.sh                  the shipped pair      MUST PASS (exit 0)
#   fake-translate-bash-only.sh        stub: Bash only       MUST PASS (exit 0)
#   fake-translate-operations-only.sh  stub: full tool map,  MUST PASS (exit 0)
#                                      no edits/reads          — see that file
#   fake-translate-mapped.sh           stub: full map AND    MUST FAIL (exit 1)
#                                      edits/reads
#
# A gate that cannot fail is not evidence, so `fake-translate-mapped.sh` is not
# optional documentation — it is the discrimination check.
#
# MEASURED 2026-09-16 on this branch. Exit codes recorded from the run, not
# predicted from the design — and one of them WAS predicted, wrongly, which is
# the whole reason this table is measured:
#
#   real-translate.sh                   exit 0   inert set == expectation
#   fake-translate-bash-only.sh         exit 0   reproduces the same five
#   fake-translate-operations-only.sh   exit 0   PREDICTED 1 — nothing revived
#   fake-translate-mapped.sh            exit 1   10 assertions, both directions
#
# And three hand-breaks, each restored by hand rather than by `git checkout`,
# which would have taken the uncommitted gate with it:
#
#   CodexAdapter._parse_tool taught to map Edit AND build edits
#                                       exit 1   8 assertions; four builtins
#                                                left the inert set, and
#                                                pre-tool-use-read-size
#                                                correctly stayed in it because
#                                                `Read` was still unmapped
#   a tool-reading builtin added to the registry and to neither expected list
#                                       exit 2   before any payload was fed
#   an expected-list entry renamed so the registry no longer has it
#                                       exit 2   and it reported BOTH that and
#                                                the hook thereby left unlisted,
#                                                rather than stopping at the
#                                                first
#
# ---------------------------------------------------------------------------
# HOW "INERT" IS ATTRIBUTED, AND WHERE THAT ATTRIBUTION COULD BE WRONG.
# ---------------------------------------------------------------------------
# An operation counts as DEGRADED if the Codex `ToolCall` lost anything the
# Claude Code one carried: `operation` went to None, or `edits`/`reads` came back
# shorter. That is a property of the TRANSLATION, and the gate then attributes
# inertness to the HOOK. The two are only the same claim if the hook actually
# reads the field that was lost.
#
# Today they coincide, and that is measured rather than assumed: every one of the
# seven tool-reading builtins consumes `edits` or `reads`, not merely the
# `operation` enum — which is what the two runs above establish for the two hooks
# where it was least obvious. A future builtin gating on `operation` alone and
# never touching the structures would be reported inert here while still doing
# its work. It would be a false positive, it would fail loudly rather than pass
# quietly, and the fix is to measure that hook's behaviour the way those two were
# measured and move it to EXPECTED_LIVE with the evidence.
#
# F8_GATE_PYTHON overrides the interpreter. Exit codes: 0 pass, 1 assertion
# failure, 2 harness error (the gate could not establish its own scope).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRANSLATOR="${1:-$HERE/real-translate.sh}"

# AN UNUSABLE SHIM PATH IS A HARNESS ERROR, NEVER A FAILED ASSERTION.
#
# This is F7's scar, transplanted. `isolation-gate.sh` invoked with a RELATIVE
# shim path from the repo root ran a shim that then wrote nothing anywhere the
# gate watched, and reported 44 FAILED ASSERTIONS — a control that must pass,
# failing, looking exactly like a regression in the thing under test. The cost
# was not the failure, it was that the failure was indistinguishable from a real
# one. Measured here on both hazards, and both refuse with exit 2 before a single
# assertion runs:
#
#   ./translation-gate.sh fake-translate-mapped.sh   (relative, from repo root)
#     -> "translator not found or not executable", exit 2
#   a translator that resolves and emits nothing
#     -> "translator returned 0 records for 18 sent", exit 2
#
# The path is resolved to an absolute one and the diagnostic names what was
# looked for, so a relative path explains itself rather than being reported as
# something the adapters did.
if [ ! -x "$TRANSLATOR" ]; then
  echo "harness error: translator not found or not executable: '$TRANSLATOR'" >&2
  echo "  resolved against cwd: $(pwd)" >&2
  echo "  a RELATIVE shim path is the known trap here — pass an absolute one," >&2
  echo "  e.g. \$PWD/fake-translate-mapped.sh. This is refused up front rather" >&2
  echo "  than reported as failed assertions, which is how it read in F7." >&2
  exit 2
fi
TRANSLATOR="$(cd "$(dirname "$TRANSLATOR")" && pwd)/$(basename "$TRANSLATOR")"

# --- the interpreter that can see the build under test ---------------------
# Ordered nearest-first: an explicit override, then the venv of the checkout this
# script lives in, then whatever ships beside an installed `lh`. Each candidate
# has to prove it can import the package; a `python3` that cannot is not a
# fallback, it is a different answer.
derive_python() {
  local cand
  for cand in \
    "${F8_GATE_PYTHON:-}" \
    "$HERE/../../../.venv/bin/python3" \
    "$(command -v lh >/dev/null 2>&1 && dirname "$(command -v lh)")/python3"
  do
    [ -n "$cand" ] && [ -x "$cand" ] || continue
    "$cand" -c 'import lazy_harness' >/dev/null 2>&1 && { echo "$cand"; return 0; }
  done
  return 1
}

GATE_PYTHON="$(derive_python)" || {
  echo "harness error: no interpreter able to import lazy_harness." >&2
  echo "  tried: \$F8_GATE_PYTHON, $HERE/../../../.venv/bin/python3, and the" >&2
  echo "  python3 beside an installed lh. The asserted set and the lane split" >&2
  echo "  are DERIVED from the registry; without it this gate would guess, so" >&2
  echo "  it refuses instead." >&2
  exit 2
}
export F8_GATE_PYTHON="$GATE_PYTHON"

echo "F8 translation gate"
echo "  translator: $TRANSLATOR"
echo "  python:     $GATE_PYTHON"
echo

# --- deriving the scope from the registry ----------------------------------
# `list_builtin_hooks()` is the public read side. `operations` is not, and the
# comment above says why that private read is here rather than guessed.
REGISTRY="$("$GATE_PYTHON" -c '
from lazy_harness.hooks.loader import _BUILTIN_HOOKS, list_builtin_hooks

for name in sorted(list_builtin_hooks()):
    ops = sorted(op.value for op in _BUILTIN_HOOKS[name].operations)
    print(name, ",".join(ops) if ops else "-")
' 2>/dev/null)"
[ -n "$REGISTRY" ] || { echo "harness error: registry query returned nothing" >&2; exit 2; }

# --- the checked-in expectation --------------------------------------------
# The gate FAILS ON ANY DIFFERENCE IN EITHER DIRECTION against these two lists:
# a builtin that became inert, and a builtin that stopped being inert. It does
# not count and pass. ADR-041's own recorded lesson is that counting a gap
# rather than failing it is what kept the gap invisible for a release, and a
# gate that reports "5 inert" while the membership churns underneath reproduces
# exactly that.
#
# A builtin leaving EXPECTED_INERT is good news and still fails: somebody
# changed translation behaviour and this file has to say so, with the reason,
# before the gate goes green again.
EXPECTED_INERT=(
  post-tool-use-ansible-lint
  post-tool-use-format
  post-tool-use-sync-claude
  pre-tool-use-memory-size
  pre-tool-use-read-size
)
EXPECTED_LIVE=(
  pre-tool-use-git-scope
  pre-tool-use-security
)

declare -a REGISTERED=() NO_TOOL=() TOOL_HOOKS=() TOOL_OPS=()
while read -r name ops; do
  [ -n "$name" ] || continue
  REGISTERED+=("$name")
  # A `case` with an explicit `*)`, not `[ "$ops" = - ] && A || B`. That idiom
  # has no third outcome: every value that is not the one tested lands in the
  # else arm silently, which is how F7 lost half a coverage assertion and
  # reintroduced the leak PR #328 had fixed. Here the silent absorption would
  # be worse, not better: an unreadable `operations` would park a tool-reading
  # builtin in NO_TOOL, where it is "accounted for" and never fed, and the gate
  # would go green over a builtin it never looked at.
  case "$ops" in
    -)  NO_TOOL+=("$name") ;;
    "") echo "harness error: registry row '$name' carries no operations field" >&2; exit 2 ;;
    *)  TOOL_HOOKS+=("$name"); TOOL_OPS+=("$ops") ;;
  esac
done <<< "$REGISTRY"

# --- COVERAGE, asserted before anything runs -------------------------------
# Every later assertion is scoped by these lanes. A name that fell out of all of
# them cannot fail a check it is never fed to, and the run would then be
# reporting on a smaller question than the one it names. Four directions, none a
# restatement of another.
COVERAGE_ERRORS=0
note_coverage() { echo "harness error: $1" >&2; COVERAGE_ERRORS=$((COVERAGE_ERRORS + 1)); }

accounted=$(( ${#NO_TOOL[@]} + ${#TOOL_HOOKS[@]} ))
[ "$accounted" -eq "${#REGISTERED[@]}" ] || \
  note_coverage "$accounted of ${#REGISTERED[@]} registered builtins accounted for"

# Both expected lists are audited against the registry, so a hook that was
# renamed or deleted fails here rather than quietly shrinking the asserted set.
for expected in "${EXPECTED_INERT[@]}" "${EXPECTED_LIVE[@]}"; do
  case " ${REGISTERED[*]} " in
    *" $expected "*) ;;
    *) note_coverage "expected list names '$expected', which the registry does not" ;;
  esac
done

# ...and in the other direction: an expected name that the registry HAS but that
# declares no operations would never be fed, so it could never be confirmed.
for expected in "${EXPECTED_INERT[@]}" "${EXPECTED_LIVE[@]}"; do
  case " ${NO_TOOL[*]} " in
    *" $expected "*) note_coverage "expected list names '$expected', which declares no operations and is never fed" ;;
  esac
done

# Every tool-reading builtin must appear in exactly one expected list. Without
# this a builtin added to the registry and to neither list would compute a
# verdict that is compared against nothing.
for hook in "${TOOL_HOOKS[@]}"; do
  seen=0
  case " ${EXPECTED_INERT[*]} " in *" $hook "*) seen=$((seen + 1)) ;; esac
  case " ${EXPECTED_LIVE[*]} " in *" $hook "*) seen=$((seen + 1)) ;; esac
  case "$seen" in
    1) ;;
    0) note_coverage "tool-reading builtin '$hook' is in neither expected list" ;;
    *) note_coverage "tool-reading builtin '$hook' is in both expected lists" ;;
  esac
done

[ "$COVERAGE_ERRORS" -eq 0 ] || exit 2

echo "coverage: ${#REGISTERED[@]} registered = ${#TOOL_HOOKS[@]} tool-reading + ${#NO_TOOL[@]} no-tool"
echo "          no-tool (accounted, never fed): ${NO_TOOL[*]}"
echo

# --- payloads, one per declared operation ----------------------------------
# Claude Code's dialect, which `CodexAdapter.parse_hook_input` documents as the
# shape Codex also delivers. An `Operation` member with no payload here exits 2
# rather than defaulting: a new member silently skipped is a whole operation
# nobody measures.
payload_for_operation() {
  case "$1" in
    run_command) printf '{"tool_name":"Bash","tool_input":{"command":"echo f8-probe"}}' ;;
    read_file)   printf '{"tool_name":"Read","tool_input":{"file_path":"/f8/probe.py"}}' ;;
    modify_file) printf '{"tool_name":"Edit","tool_input":{"file_path":"/f8/probe.py","old_string":"a","new_string":"b"}}' ;;
    *) echo "harness error: no payload for operation '$1'" >&2; exit 2 ;;
  esac
}

RECORDS=""
for i in "${!TOOL_HOOKS[@]}"; do
  hook="${TOOL_HOOKS[$i]}"
  IFS=',' read -r -a ops <<< "${TOOL_OPS[$i]}"
  for op in "${ops[@]}"; do
    payload="$(payload_for_operation "$op")"
    RECORDS+="$hook	$op	claude-code	$payload"$'\n'
    RECORDS+="$hook	$op	codex	$payload"$'\n'
  done
done

RESULTS="$(printf '%s' "$RECORDS" | "$TRANSLATOR")" || {
  echo "harness error: translator failed: $TRANSLATOR" >&2
  exit 2
}

expected_lines=$(printf '%s' "$RECORDS" | grep -c '' || true)
got_lines=$(printf '%s' "$RESULTS" | grep -c '' || true)
[ "$got_lines" -eq "$expected_lines" ] || {
  echo "harness error: translator returned $got_lines records for $expected_lines sent" >&2
  exit 2
}

# --- comparison -------------------------------------------------------------
FAILURES=0
declare -a FAIL_LINES=() COMPUTED_INERT=() COMPUTED_LIVE=() PARTIAL=()
fail() { FAILURES=$((FAILURES + 1)); FAIL_LINES+=("$1"); echo "  FAIL: $1"; }
ok()   { echo "  ok:   $1"; }
info() { echo "  --    $1"; }

field() { printf '%s\n' "$RESULTS" | awk -F'\t' -v h="$1" -v o="$2" -v a="$3" -v n="$4" \
  '$1==h && $2==o && $3==a { print $(4+n) }'; }

echo "translation, per declared operation:"
for i in "${!TOOL_HOOKS[@]}"; do
  hook="${TOOL_HOOKS[$i]}"
  IFS=',' read -r -a ops <<< "${TOOL_OPS[$i]}"
  degraded_count=0
  survived_count=0
  for op in "${ops[@]}"; do
    c_name="$(field "$hook" "$op" claude-code 0)"
    c_op="$(field "$hook" "$op" claude-code 1)"
    c_edits="$(field "$hook" "$op" claude-code 2)"
    c_reads="$(field "$hook" "$op" claude-code 3)"
    x_name="$(field "$hook" "$op" codex 0)"
    x_op="$(field "$hook" "$op" codex 1)"
    x_edits="$(field "$hook" "$op" codex 2)"
    x_reads="$(field "$hook" "$op" codex 3)"

    [ -n "$c_name" ] && [ -n "$x_name" ] || {
      echo "harness error: no record back for $hook/$op" >&2; exit 2; }

    # `native_name` is asserted EQUAL rather than folded into degradation. A
    # translation that renames the tool is a different defect with a different
    # fix, and a hook gating on `INSPECTED_TOOLS` would miss it for a reason
    # that has nothing to do with an emptied structure.
    if [ "$c_name" != "$x_name" ]; then
      fail "$hook/$op: native_name differs — claude '$c_name' vs codex '$x_name'"
    fi

    # `if`, not `[ A ] && [ B ] && reasons+=...`. Under `set -euo pipefail` that
    # chain evaluates to 1 whenever the guard is false and takes the whole gate
    # down with it — a checker that exits on its own passing case. Measured: the
    # first draft died silently on `pre-tool-use-git-scope`, the first builtin
    # whose operation survives.
    reasons=""
    if [ "$c_op" != "NONE" ] && [ "$x_op" = "NONE" ]; then
      reasons+="operation($c_op->NONE) "
    fi
    if [ "$c_edits" -gt "$x_edits" ]; then
      reasons+="edits($c_edits->$x_edits) "
    fi
    if [ "$c_reads" -gt "$x_reads" ]; then
      reasons+="reads($c_reads->$x_reads) "
    fi

    case "$reasons" in
      "") survived_count=$((survived_count + 1))
          info "$hook/$op: survives (op=$x_op edits=$x_edits reads=$x_reads)" ;;
      *)  degraded_count=$((degraded_count + 1))
          info "$hook/$op: DEGRADED — ${reasons% }" ;;
    esac
  done

  case "$survived_count" in
    0) COMPUTED_INERT+=("$hook") ;;
    *) COMPUTED_LIVE+=("$hook")
       if [ "$degraded_count" -gt 0 ]; then
         PARTIAL+=("$hook ($degraded_count of $((degraded_count + survived_count)) declared operations degraded)")
       fi ;;
  esac
done
echo

# --- the assertion, both directions ----------------------------------------
echo "inert set vs checked-in expectation:"
# Takes the two sets as space-padded strings rather than by nameref, which needs
# bash 4.3 — F7 runs on whatever bash the machine has and this sibling should
# not raise that floor.
assert_same_set() {
  local label="$1" expected=" $2 " computed=" $3 " entry
  for entry in $expected; do
    case "$computed" in
      *" $entry "*) ok "$label: '$entry' as expected" ;;
      *) fail "$label: '$entry' is expected but was NOT computed — it stopped being $label" ;;
    esac
  done
  for entry in $computed; do
    case "$expected" in
      *" $entry "*) ;;
      *) fail "$label: '$entry' was computed but is NOT in the expected list — it became $label" ;;
    esac
  done
}

assert_same_set INERT "${EXPECTED_INERT[*]}" "${COMPUTED_INERT[*]:-}"
assert_same_set LIVE "${EXPECTED_LIVE[*]}" "${COMPUTED_LIVE[*]:-}"
echo

# --- recorded, never asserted ----------------------------------------------
# A builtin that is LIVE on one declared operation and degraded on another. It
# is not inert — it has a reachable branch and can still refuse — so it does not
# belong in the set above, and asserting on it here would put two questions
# behind one exit code. It is printed because a guard that enforces half its
# denylist and is silent on the other half is indistinguishable, from outside,
# from one that passed.
echo "recorded, not asserted — partially degraded builtins:"
if [ "${#PARTIAL[@]}" -eq 0 ]; then
  echo "  (none)"
else
  for entry in "${PARTIAL[@]}"; do echo "  $entry"; done
fi
echo

echo "computed INERT: ${COMPUTED_INERT[*]:-(none)}"
echo "computed LIVE:  ${COMPUTED_LIVE[*]:-(none)}"
echo
if [ "$FAILURES" -eq 0 ]; then
  echo "PASS — $((${#TOOL_HOOKS[@]})) tool-reading builtins, inert set matches the expectation exactly."
  exit 0
fi
echo "FAIL — $FAILURES assertion(s):"
for line in "${FAIL_LINES[@]}"; do echo "  - $line"; done
exit 1
