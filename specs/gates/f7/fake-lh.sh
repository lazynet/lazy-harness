#!/usr/bin/env bash
# Shared body of the two control shims for isolation-gate.sh. Not run directly:
# `fake-lh-fixed.sh` and `fake-lh-security-only.sh` set F7_FAKE_FIXED and exec
# this. It lives in one file so a change to the emulated logging channels cannot
# land in one shim and not the other — which would silently stop the gate being
# checked in both directions.
#
# F7_FAKE_FIXED is the set of hooks that resolve their evidence dir from the
# INVOKING PROFILE's config_dir. Everything else resolves globally, which is what
# a partial fix looks like. The literal `ALL` means every hook is fixed.
#
# IT ALSO EMULATES THE ADAPTER'S ABSTENTION, and that is not decoration. Until
# 2026-09-15 this shim logged a line for every hook on every payload, so BOTH
# fixtures passed their directions while the real binary failed 28 assertions:
# the gate fed a Claude Code payload to a profile declaring `agent = "codex"`,
# `CodexAdapter._TOOL_OPERATIONS` maps only `Bash -> RUN_COMMAND`
# (`codex.py:92`), and every hook gating on `operation is MODIFY_FILE` abstained
# and wrote nothing. A shim that always writes cannot see that, which is how the
# defect shipped. `abstains` below reproduces it, so the fixtures now cover the
# failure class the gate was repaired for.
set -uo pipefail

FIXED="${F7_FAKE_FIXED:?F7_FAKE_FIXED must be set by the calling shim}"

[ "${1:-}" = "--version" ] && { echo "lazy-harness, version 0.0.0-fake (fixed: $FIXED)"; exit 0; }
[ "${1:-}" = "hook" ] || exit 0
HOOK="$2"; PROFILE=""
[ "${3:-}" = "--profile" ] && PROFILE="${4:-}"
PAYLOAD="$(cat)"

is_fixed() {
  [ "$FIXED" = ALL ] && return 0
  case " $FIXED " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

CFG="${LH_CONFIG_DIR:-}/config.toml"

profile_field() {
  [ -f "$CFG" ] || return 0
  awk -v p="[profiles.$PROFILE]" -v k="$1" '
    $0==p {inb=1; next} /^\[/ {inb=0}
    inb && $1==k {gsub(/.*= *"|"$/,""); print; exit}' "$CFG"
}

# The adapter's abstention, emulated. A hook reasoning about a tool call reads
# `event.tool.operation`, and the codex adapter resolves an operation for `Bash`
# alone — so under a codex profile any other tool arrives as
# `ToolCall(operation=None, edits=())` and the hook returns an empty decision
# without touching a file. A payload naming no tool at all is a lifecycle event,
# which crosses both adapters unchanged.
abstains() {
  local tool
  tool="$(printf '%s' "$PAYLOAD" | sed -n 's/.*"tool_name":"\([^"]*\)".*/\1/p')"
  [ -n "$tool" ] || return 1
  [ "$tool" = Bash ] && return 1
  [ "$(profile_field agent)" = codex ]
}
abstains && exit 0

DIR=""
if is_fixed "$HOOK" && [ -n "$PROFILE" ] && [ -f "$CFG" ] && grep -q '^\[harness\]' "$CFG" 2>/dev/null; then
  DIR="$(profile_field config_dir)"
fi
[ -z "$DIR" ] && DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"   # global / degraded fallback

field() { printf '%s' "$PAYLOAD" | sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p"; }
FP="$(field file_path)"; CMD="$(field command)"; CWD="$(field cwd)"; [ -z "$CWD" ] && CWD="$PWD"

mkdir -p "$DIR/logs"

# engram-persist writes no hooks.log line. Its token-bearing channel is the
# metrics JSONL, keyed by the cwd basename as `project_key` — emulated here so
# the gate's engram-persist assertion has something to find.
if [ "$HOOK" = engram-persist ]; then
  printf '{"ts": "%s", "event": "skip", "reason": "binary_not_found", "project_key": "%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(basename "$CWD")" \
    >> "$DIR/logs/engram_persist_metrics.jsonl"
  exit 0
fi

case "$HOOK" in
  context-inject)             NAME=session-context; MSG="fired cwd=$CWD" ;;
  pre-tool-use-security)      NAME=$HOOK; MSG="blocked filesystem: $CMD" ;;
  pre-tool-use-git-scope)     NAME=$HOOK; MSG="blocked git-scope: $CMD" ;;
  pre-tool-use-memory-size)   NAME=$HOOK; MSG="over threshold: $FP would be 301 lines (threshold 200)" ;;
  pre-tool-use-read-size)     NAME=$HOOK; MSG="unbounded read: $FP 600 lines ~9000 tokens" ;;
  post-tool-use-format)       NAME=$HOOK; MSG="ruff unavailable (FileNotFoundError), left $FP unformatted" ;;
  post-tool-use-ansible-lint) NAME=$HOOK; MSG="ansible-lint unavailable (FileNotFoundError), left $FP unchecked" ;;
  *)                          NAME=$HOOK; MSG="fired cwd=$CWD" ;;
esac

echo "$(date +%Y-%m-%dT%H:%M:%S%z) $NAME: $MSG" >> "$DIR/logs/hooks.log"
[ "$HOOK" = pre-tool-use-security ] && exit 2
exit 0
