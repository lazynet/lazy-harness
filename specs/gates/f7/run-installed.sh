#!/usr/bin/env bash
# F7 against the installed binary, mapped onto the three agent shapes the user
# runs day to day: `lazy` (claude-code), `flex` (claude-code) and `lazy-codex`
# (codex).
#
# `isolation-gate.sh` takes only a binary path (`isolation-gate.sh
# [path-to-lh]`) and has no notion of a real profile name: it always builds
# two THROWAWAY profiles of its own, one per ADAPTER —
# `gate-throwaway-codex` and `gate-throwaway-claude` — and returns ONE
# combined PASS/FAIL for both lanes together from a single execution
# (`isolation-gate.sh:765`, `FAILURES` summed over both lanes). `lazy` and
# `flex` both dispatch through the claude-code adapter, so they are the SAME
# lane as far as this gate can tell apart — a second execution "for flex"
# would build a byte-identical throwaway profile and re-run the identical two
# lanes, at full runtime (~17s even against a shell stub), for no new signal.
#
# So this script runs the gate ONCE and reports that one execution's result
# under all three shape names, instead of pretending three independent checks
# happened. A caller who needs to know WHICH lane failed reads the shared
# output file — the gate's own FAIL lines are grouped by "codex"/"claude".
#
# Usage:
#   ./run-installed.sh [path-to-lh]     (default: ~/.local/bin/lh)
# Env:
#   F7_RUN_INSTALLED_GATE     path to isolation-gate.sh (default: the copy
#                             beside this script)
#   F7_RUN_INSTALLED_OUT_DIR  where the per-shape files land (default: /tmp)
#   F7_GATE_ROOT, F7_GATE_PYTHON  passed through unchanged to isolation-gate.sh
# Exit:
#   0 = PASS on all shapes, 1 = the gate failed, 2 = harness error
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE_SH="${F7_RUN_INSTALLED_GATE:-$SCRIPT_DIR/isolation-gate.sh}"
OUT_DIR="${F7_RUN_INSTALLED_OUT_DIR:-/tmp}"
LH_BIN_ARG="${1:-$HOME/.local/bin/lh}"

# Same absolute-path rule as isolation-gate.sh's own binary guard, and for the
# same reason: a relative path here would be resolved against THIS shell's
# cwd, which is not what a caller sourcing this from an arbitrary directory
# expects, and isolation-gate.sh would then re-derive the same exit-2 anyway.
case "$LH_BIN_ARG" in
  /*) ;;
  *)
    echo "run-installed: pass an absolute path to lh (got: $LH_BIN_ARG)" >&2
    exit 2
    ;;
esac
[ -x "$LH_BIN_ARG" ] || {
  echo "run-installed: $LH_BIN_ARG is not executable" >&2
  exit 2
}
[ -x "$GATE_SH" ] || {
  echo "run-installed: $GATE_SH is not executable (F7_RUN_INSTALLED_GATE override?)" >&2
  exit 2
}
[ -d "$OUT_DIR" ] || {
  echo "run-installed: F7_RUN_INSTALLED_OUT_DIR=$OUT_DIR is not a directory" >&2
  exit 2
}

# A loose file dropped directly into a world-writable $OUT_DIR (the /tmp
# default) is a resource with no boundary of its own: anything else with
# access to that directory can read or replace it. SCRATCH is a private,
# mode-0700 directory (mktemp -d's default), so only this user can see what
# lands inside it. Nested under $OUT_DIR rather than the system tmp default so
# the final `mv` below is a same-filesystem rename, not a cross-filesystem
# copy.
SCRATCH="$(mktemp -d "$OUT_DIR/.f7-scratch.XXXXXX")" || {
  echo "run-installed: could not create a scratch directory under $OUT_DIR" >&2
  exit 2
}
trap 'rm -rf -- "$SCRATCH"' EXIT

set +e
GATE_OUTPUT="$("$GATE_SH" "$LH_BIN_ARG" 2>&1)"
GATE_EXIT=$?
set -e

if [ "$GATE_EXIT" -eq 0 ]; then
  VERDICT=PASS
else
  VERDICT=FAIL
fi

echo "F7 run-installed: one isolation-gate.sh execution, mapped onto three shapes"
echo "binary:    $LH_BIN_ARG"
echo "gate:      $GATE_SH"
echo "gate exit: $GATE_EXIT"
echo

# lazy/flex share the claude-code adapter and therefore the gate's single
# "claude lane" (see the header above) — lazy-codex is the codex lane. Both
# lanes already ran together above; this loop documents the mapping and fans
# the one execution's evidence out to per-shape files, it does not re-derive
# a lane-specific verdict the gate itself does not expose.
#
# The f7-<shape>.txt names ARE stable (callers look for them) in a directory
# other users can write to, so a symlink could already be sitting at one of
# them. Checking for that first and then writing would still race — the
# symlink could appear in the gap between the check and the write. Writing
# inside SCRATCH and `mv`-ing into place instead has no such gap: `mv` (a
# rename(2)) replaces whatever directory entry is at the destination — file,
# symlink, or nothing — without ever opening or following it.
declare -A SHAPE_LANE=([lazy]=claude [flex]=claude [lazy-codex]=codex)
for shape in lazy flex lazy-codex; do
  dest="$OUT_DIR/f7-$shape.txt"
  tmp_dest="$SCRATCH/f7-$shape.txt"
  printf '%s\n' "$GATE_OUTPUT" >"$tmp_dest"
  mv -f -- "$tmp_dest" "$dest"
  echo "$shape (${SHAPE_LANE[$shape]} lane): $VERDICT -> $dest"
done

[ "$GATE_EXIT" -eq 0 ] || exit 1
