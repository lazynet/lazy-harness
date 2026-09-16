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
# WHY A MAPPING FIX IS NOT A FIX — and the two corrections this gate produced.
# ---------------------------------------------------------------------------
# FIRST CORRECTION, 2026-09-16. The prevailing account, in `specs/backlog.md`
# and in the brief that commissioned this gate, was that the five inert builtins
# fail by TWO mechanisms: `post-tool-use-format` and `pre-tool-use-read-size` at
# the `operation` gate, the other three one step lower at `tool.edits`. That
# account was right about where each hook returns FIRST and wrong about what
# follows from it. Measured by running the hooks, not by reading them:
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
# The operation gate is the first of TWO gates in those two hooks. So all five
# needed the STRUCTURE, and `fake-translate-operations-only.sh` — that change,
# emulated — was written expecting this gate to fail it and PASSED: the mapping
# fix was not a partial fix, it was a no-op.
#
# SECOND CORRECTION, the same day, and it is why the expected sets below moved.
# Both findings above were reached with the gate feeding CLAUDE CODE'S DIALECT
# to both translators. `specs/designs/codex-evidence.md` then measured what
# Codex actually sends, and the payloads changed to match: `apply_patch`, with
# the patch text under `tool_input.command`. Against that dialect the real
# adapter's three TRANSLATION fixes — the tool map, `_shared.EDIT_TOOLS`, and a
# parser for the blob — take four builtins out of the inert set, and
# `fake-translate-operations-only.sh` FLIPS TO EXIT 1. That flip is now the
# gate's discrimination check: it is the same "map everything, build nothing"
# change, and it is the measurement that says the parser is the load-bearing
# third of the three rather than the tidy-up.
#
# THREE HERE, FOUR IN ADR-044, and the difference is this gate's scope rather
# than a disagreement. A fourth fix was needed inside
# `pre_tool_use_memory_size._projected_text`, which branches on the tool name and
# went quiet on `apply_patch` with the three above in place. This gate measures
# the TRANSLATION — what a `ToolCall` carries — so a gate downstream of it, in
# one builtin's own body, is invisible here by construction. `LIVE` in the sets
# below means "the structure survives", never "the hook acts".
#
# Neither correction reverses the other. A mapping fix alone still revives
# nothing; what changed is that there is now something else in the tree for it
# to be insufficient *against*.
#
# ---------------------------------------------------------------------------
# WHAT THIS GATE DOES NOT MEASURE — read this before trusting a green run.
# ---------------------------------------------------------------------------
# Both sides of every comparison are PYTHON OBJECTS: the shipped
# `ClaudeCodeAdapter` and the shipped `CodexAdapter`. The `codex` binary is never
# invoked here. What changed on 2026-09-16 is the INPUT: the payloads are no
# longer Claude Code's dialect on both legs. The Codex leg is fed what six probes
# against `codex-cli 0.154.0` observed it send, transcribed into
# `specs/designs/codex-evidence.md` and copied from there. So a green run now
# says the shipped pair agrees with this file's expectations ON A PAYLOAD THE
# BINARY WAS SEEN TO PRODUCE — which is strictly more than it used to say, and
# still not a claim about the binary's behaviour at run time.
#
# THREE THINGS IT STILL DOES NOT MEASURE, each for its own reason:
#
#   The `Bash` edit path. Codex picks between `apply_patch` and a `Bash` python
#   heredoc non-deterministically, and the heredoc CANNOT be fed here as an
#   edit: `tool_input` is an arbitrary shell script with no path to extract.
#   Half of Codex's edits are ungateable and no expectation below covers them.
#
#   Codex's read dialect. No probe has caught Codex reading a file, so the
#   `read_file` leg is the one synthetic payload left and
#   `pre-tool-use-read-size`'s inert verdict rests on it.
#
#   Multi-file blobs. Whether Codex concatenates several `*** Update File:`
#   sections into one call is plausible and untested (evidence §2). The parser
#   is generic over sections; this gate feeds one.
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
#   fake-translate-bash-only.sh        stub: Bash only       MUST FAIL (exit 1)
#   fake-translate-operations-only.sh  stub: full tool map,  MUST FAIL (exit 1)
#                                      no edits/reads          — see that file
#   fake-translate-mapped.sh           stub: full map AND    MUST FAIL (exit 1)
#                                      file_path structures
#
# A gate that cannot fail is not evidence, and a gate that fails everything is
# not evidence either. `real-translate.sh` is the must-pass half; the three
# stubs are the must-fail half, and they fail for three DIFFERENT reasons, which
# is what keeps the pair from degenerating into "anything but real is red".
#
# RE-MEASURED 2026-09-16 after the Codex leg started carrying Codex's dialect.
# Two verdicts flipped, and the flips are the finding:
#
#   real-translate.sh                   exit 0   inert set == expectation
#   fake-translate-bash-only.sh         exit 1   was 0. The pre-step-9 adapter,
#                                                emulated: four builtins fall
#                                                back into the inert set
#   fake-translate-operations-only.sh   exit 1   was 0, and this is THE
#                                                discrimination check — map
#                                                every name, parse no blob, and
#                                                the same four go inert. The
#                                                parser is load-bearing
#   fake-translate-mapped.sh            exit 1   fails in BOTH directions now:
#                                                it reads `file_path`, which
#                                                Codex's edit dialect does not
#                                                carry (four became inert) while
#                                                the synthetic `Read` payload
#                                                does (read-size stopped being)
#
# And four hand-breaks, each restored by hand rather than by `git checkout`,
# which would have taken the uncommitted gate with it:
#
#   CodexAdapter._parse_tool taught to map Edit AND build edits
#                                       exit 1   8 assertions; four builtins
#                                                left the inert set, and
#                                                pre-tool-use-read-size
#                                                correctly stayed in it because
#                                                `Read` was still unmapped
#   _parse_patch made to invent a FileEdit for a blob naming no file
#                                       exit 1   5 assertions, all from the
#                                                must-abstain leg — the half of
#                                                the parser's contract the
#                                                expected sets cannot express
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
#
# FOUR BUILTINS LEFT EXPECTED_INERT ON 2026-09-16, and the rule above is why
# this comment exists rather than a smaller list appearing silently. They left
# because the Codex leg is now fed Codex's real edit dialect AND the shipped
# adapter parses it: `apply_patch` maps to `MODIFY_FILE`, the four edit builtins
# carry `apply_patch` in `_shared.EDIT_TOOLS`, and `_parse_patch` turns the blob
# into `FileEdit`s. Each of the three was necessary; the gate's own
# `fake-translate-operations-only.sh` is the proof that the first two without
# the third revive nothing.
#
# `pre-tool-use-read-size` stays, and its verdict is the weakest one here: no
# probe has caught Codex reading a file, so its leg is still fed Claude's
# `Read` payload. It says the adapter maps no tool named `Read` — not that
# Codex's real read path is ungated, which nobody has measured.
EXPECTED_INERT=(
  pre-tool-use-read-size
)
EXPECTED_LIVE=(
  post-tool-use-ansible-lint
  post-tool-use-format
  post-tool-use-sync-claude
  pre-tool-use-git-scope
  pre-tool-use-memory-size
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

# --- payloads, one per declared operation PER AGENT ------------------------
# EACH AGENT IS FED ITS OWN DIALECT. Until 2026-09-16 this function took one
# argument and both translators were handed Claude Code's literal payload
# `{"tool_name":"Edit",...}`. That measured "what happens if Codex sent Claude's
# tool name", never what Codex sends — and the answer, from six probes against
# `codex-cli 0.154.0` recorded in `specs/designs/codex-evidence.md`, is neither
# `Edit` nor anything like it.
#
# Codex takes TWO edit paths and picks between them non-deterministically:
# `Bash` running a python heredoc, and its own `apply_patch`. The native one
# arrives as `tool_name: "apply_patch"` with `tool_input.command` holding a raw
# patch blob — the SAME key `Bash` uses — and the touched path embedded as a
# `*** Update File:` line inside the text, never as a structured field. That is
# probe 4c, confirmed by a validated deny that actually blocked the edit.
#
# The `Bash` path is not fed here and cannot be: `tool_input` is an arbitrary
# shell script with no path to extract, so it is a command whatever it writes.
# Half of Codex's edits are structurally ungateable, which this gate cannot fix
# and must not paper over.
#
# `read_file` under Codex is THE ONE SYNTHETIC LEG LEFT: no probe has caught
# Codex reading a file, so there is no dialect to feed. It gets Claude's `Read`
# payload, and `pre-tool-use-read-size`'s inert verdict is therefore weaker
# evidence than the other six — it says the adapter maps no tool named `Read`,
# not that Codex's real read path is ungated.
#
# An `Operation` member with no payload here exits 2 rather than defaulting: a
# new member silently skipped is a whole operation nobody measures.
PATCH_BLOB='*** Begin Patch\n*** Update File: /f8/probe.py\n@@\n-a\n+b\n*** End Patch'
# The same blob with its file section removed. `edits` must come back empty and
# every builtin gated on it must abstain — the must-fail half of the parser's
# contract, asserted below rather than recorded.
BLOBLESS='*** Begin Patch\n@@\n-a\n+b\n*** End Patch'

payload_for_operation() {
  case "$2/$1" in
    */run_command) printf '{"tool_name":"Bash","tool_input":{"command":"echo f8-probe"}}' ;;
    */read_file)   printf '{"tool_name":"Read","tool_input":{"file_path":"/f8/probe.py"}}' ;;
    claude-code/modify_file)
      printf '{"tool_name":"Edit","tool_input":{"file_path":"/f8/probe.py","old_string":"a","new_string":"b"}}' ;;
    codex/modify_file)
      printf '{"tool_name":"apply_patch","tool_input":{"command":"%s"}}' "$PATCH_BLOB" ;;
    codex-blobless/modify_file)
      printf '{"tool_name":"apply_patch","tool_input":{"command":"%s"}}' "$BLOBLESS" ;;
    *) echo "harness error: no payload for operation '$1' under agent '$2'" >&2; exit 2 ;;
  esac
}

# The tool name each payload DECLARES, derived by parsing the payload rather
# than by a second table beside `payload_for_operation`. Two tables is how the
# assertion below would start checking a name nothing is fed.
NAME_FOR=""
for agent in claude-code codex codex-blobless; do
  for op in run_command read_file modify_file; do
    [ "$agent" = codex-blobless ] && [ "$op" != modify_file ] && continue
    declared_name="$(payload_for_operation "$op" "$agent" \
      | "$GATE_PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["tool_name"])')"
    NAME_FOR+="$agent	$op	$declared_name"$'\n'
  done
done
declared_name() {
  printf '%s\n' "$NAME_FOR" | awk -F'\t' -v a="$1" -v o="$2" '$1==a && $2==o { print $3 }'
}

RECORDS=""
for i in "${!TOOL_HOOKS[@]}"; do
  hook="${TOOL_HOOKS[$i]}"
  IFS=',' read -r -a ops <<< "${TOOL_OPS[$i]}"
  for op in "${ops[@]}"; do
    for agent in claude-code codex; do
      RECORDS+="$hook	$op	$agent	$(payload_for_operation "$op" "$agent")"$'\n'
    done
    if [ "$op" = modify_file ]; then
      RECORDS+="$hook	$op	codex-blobless	$(payload_for_operation "$op" codex-blobless)"$'\n'
    fi
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

    # `native_name` is asserted against EACH SIDE'S OWN PAYLOAD rather than
    # across the two. It used to be `c_name = x_name`, which was the right
    # assertion only while both sides were fed the same synthetic payload: with
    # real dialects the names differ BY CONSTRUCTION — `Edit` versus
    # `apply_patch` — and keeping the old form would have failed the gate for
    # the very change that made it honest.
    #
    # The defect it was written to catch is untouched: a translation that
    # renames the tool it was handed is a different fix from one that empties a
    # structure, and a hook gating on `INSPECTED_TOOLS` would miss it for an
    # unrelated reason. Per-side fidelity catches exactly that, on both sides
    # rather than only where they happened to agree.
    for side in "claude-code:$c_name" "codex:$x_name"; do
      side_agent="${side%%:*}"
      if [ "${side#*:}" != "$(declared_name "$side_agent" "$op")" ]; then
        fail "$hook/$op: $side_agent renamed its tool — payload said \
'$(declared_name "$side_agent" "$op")', translation said '${side#*:}'"
      fi
    done

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
    # THE MUST-ABSTAIN HALF, asserted rather than recorded.
    #
    # The same tool name and the same operation arrive; only the structure is
    # missing, because the blob names no file. `edits` has to come back empty —
    # a parser that returned one here would hand five builtins a path it
    # invented. Paired with the well-formed leg above this is the gate's
    # pass/fail pair on the parser itself: remove the abstention and this goes
    # red, remove the parsing and the inert set does.
    if [ "$op" = modify_file ]; then
      b_edits="$(field "$hook" "$op" codex-blobless 2)"
      [ -n "$b_edits" ] || { echo "harness error: no blobless record for $hook" >&2; exit 2; }
      if [ "$b_edits" -ne 0 ]; then
        fail "$hook/$op: a patch blob naming no file yielded $b_edits edit(s)"
      fi
    fi
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
