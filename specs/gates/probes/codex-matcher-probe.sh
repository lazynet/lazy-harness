#!/usr/bin/env bash
# Codex CLI 0.154.0 — does a `PreToolUse` matcher fire, and in which spelling?
#
# RUN THIS FROM A PLAIN TERMINAL. Never from a Claude Code or Herdr pane: this
# repo's standing rule for agent binaries. It drives `codex exec`, which
# authenticates and executes model-proposed shell commands.
#
#   bash specs/gates/probes/codex-matcher-probe.sh
#   bash specs/gates/probes/codex-matcher-probe.sh --dry-run   # renders, spawns nothing
#
# WHY IT EXISTS. The F9 acceptance run of 2026-09-17 12:32 had all 31 deployed
# hooks approved, and three assertions still failed: the `rm -rf` fixture ran,
# the native edit wrote a denied `.env`, the file changed. The events deployed
# WITHOUT a matcher — SessionStart, Stop, SessionEnd — all fired and logged. No
# `PreToolUse` hook has ever written a line to `~/.codex-lazy/logs/hooks.log`.
# Every `PreToolUse` group the harness deploys carries a matcher, and every one
# of those matchers is Claude Code's syntax over Claude Code's tool names:
#
#   0  Bash|Read|Edit|Write|NotebookEdit     5  ExitPlanMode
#   1  Bash                                  6  Bash|Grep
#   2  Edit|Write                            7  Read|Glob
#   3  Read
#   4  AskUserQuestion
#
# `_hook_groups`'s own docstring says a literal matching no tool "suppressed the
# hook completely and silently". So the harness may have been shipping eight
# silently suppressed guards, and reading the code settles none of it. Three
# hypotheses, distinguishable only by measurement:
#
#   H1  Codex's matcher is exact-match or otherwise non-regex, so `A|B|C`
#       matches nothing while a bare `Bash` matches.
#   H2  the group fires and the payload shape makes the harness hook answer
#       allow — a blocking hook failing open, which is this repo's named gate.
#   H3  no `PreToolUse` matcher can match under Codex at all.
#
# HOW IT DISTINGUISHES THEM. One throwaway `CODEX_HOME` whose `hooks.json`
# declares one `PreToolUse` group per spelling, each writing the payloads it
# receives to its own sink and answering nothing. Two turns: one shell command,
# one native single-file edit — the same two paths F9 asserts on, and the two
# tool names `_TOOL_OPERATIONS` maps (`Bash`, `apply_patch`). Then one row per
# spelling: did it fire, how often, and with which `tool_name`.
#
# THE CONTROL GROUP IS LAST, AND THAT IS LOAD-BEARING. `none` — no `matcher`
# key — is the form measured firing on every tool call (probes 1-4c,
# `codex-evidence.md`). Emitted FIRST it would fire on everything, and a run in
# which nothing else fired could not tell "Codex evaluates only the first
# matching group" from "every other matcher matched nothing" — H1 and H3 would
# read identically. Emitted LAST, a spelling that fires proves matchers are
# honoured, and `none` firing alone proves the others were evaluated and
# rejected rather than pre-empted.
#
# `--dangerously-bypass-hook-trust` IS WHAT MAKES THIS AUTOMATABLE, and it is
# also why the throwaway home is not optional. Declared by `codex exec --help`
# on 0.154.0 — "run enabled hooks without requiring persisted hook trust". It
# is the only route past the manual TUI approval. Pointed at a real `~/.codex*`
# it would run 31 unreviewed handlers; pointed here it runs seven that append a
# line and exit.
#
# AUTH IS COPIED, the repo's measured convention rather than a shortcut:
# `auth.json` lives inside `CODEX_HOME`, so a disposable home has no credential
# at all (`codex-evidence.md:89-90` — every earlier probe copies it). The copy
# never leaves this machine and dies with the scratch home on exit.
#
# THE SUMMARY PRINTS TOOL NAMES AND COUNTS, NEVER BODIES. A `PreToolUse`
# payload carries the proposed command, the patch blob and absolute paths under
# `$HOME`. `codex_matcher_summary.py` beside this file does that half, and
# `tests/unit/test_codex_matcher_summary.py` asserts it.

set -euo pipefail

BIN="${CODEX_BIN:-codex}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUMMARY="$HERE/codex_matcher_summary.py"
OUT="${PROBE_OUT:-$(mktemp -d)}"
REAL_AUTH="${CODEX_AUTH:-$HOME/.codex/auth.json}"
# A turn that stalls on an approval it cannot receive would otherwise hang the
# whole probe. `timeout` is GNU; macOS ships it only via coreutils as `gtimeout`.
TIMEOUT_SECONDS="${PROBE_TIMEOUT:-180}"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "usage: codex-matcher-probe.sh [--dry-run]"
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null 2>&1 || { echo "no python3 on PATH" >&2; exit 2; }
[ -f "$SUMMARY" ] || { echo "missing summary printer: $SUMMARY" >&2; exit 2; }

# The spellings, in the order they are rendered — which is the order the trust
# key indexes and the order the summary table reads. `none` is last; see the
# header.
LABELS=(bare-bash alt-claude edit-write apply-patch shell regex-anchor none)

# A function rather than a parallel array because the alternation literals carry
# `|`, which several of bash 3.2's array spellings eat.
matcher_for() {
  case "$1" in
    # The two Claude Code spellings the harness deploys today, verbatim.
    bare-bash)    printf '%s' 'Bash' ;;
    alt-claude)   printf '%s' 'Bash|Read|Edit|Write|NotebookEdit' ;;
    edit-write)   printf '%s' 'Edit|Write' ;;
    # The names Codex itself puts on the wire (`_TOOL_OPERATIONS`), and the one
    # `codex exec`'s own reasoning uses for its shell tool — the harness reads
    # `Bash` in the payload, and whether the MATCHER is evaluated against the
    # same string has never been measured.
    apply-patch)  printf '%s' 'apply_patch' ;;
    shell)        printf '%s' 'shell' ;;
    # Anchored regex. If this fires and `bare-bash` does not, the matcher is a
    # regex over the whole name; if both fire, it is a substring or exact match
    # that happens to tolerate the anchors; if only `bare-bash` fires, it is not
    # a regex at all.
    regex-anchor) printf '%s' '^Bash$' ;;
    # The control: no `matcher` key at all.
    none)         printf '' ;;
    *) echo "unknown label: $1" >&2; return 2 ;;
  esac
}

SINKS="$OUT/fired"
HANDLER="$OUT/matcher_probe_hook.py"

# Everything this run creates outside `$OUT`, removed on the way out however it
# ends — including the non-zero exits a refused turn makes ordinary. The scratch
# home is the one that matters: it holds a copy of `auth.json`, which carries
# `access_token`, `refresh_token` and `id_token` (shape measured 2026-09-16,
# `codex-evidence.md` probe 8). Leaving one under `/var/folders` after the probe
# printed "done" would be a credential the user never chose to spread.
SCRATCH_DIRS=()
cleanup() {
  if [ "${#SCRATCH_DIRS[@]}" -gt 0 ]; then rm -rf "${SCRATCH_DIRS[@]}"; fi
}
trap cleanup EXIT

# The handler. One line per payload, appended to the sink named for the group's
# own label, and NOTHING on stdout.
#
# Nothing on stdout is deliberate and is not the same as answering `allow`.
# ADR-041 records that Codex rejects `allow` as an unsupported
# `permissionDecision` and then FAILS OPEN — so emitting one would measure the
# verdict parser instead of the matcher, and a suppressed group and an ignored
# verdict would again be indistinguishable. Silence is the only response whose
# meaning is not in question: the call proceeds, and the sink records that the
# group saw it.
write_handler() {
  mkdir -p "$(dirname "$1")"
  cat > "$1" <<'PY'
#!/usr/bin/env python3
"""Append one PreToolUse payload to the sink named for this group's label."""

import pathlib
import sys

label = sys.argv[1]
sinks = pathlib.Path(sys.argv[2])
sinks.mkdir(parents=True, exist_ok=True)
raw = sys.stdin.read()
# Newlines are collapsed so one payload is one JSONL line even if Codex pretty-
# prints it. Safe: a JSON string never carries a raw newline, so this cannot
# alter a value, only the framing between them.
line = " ".join(raw.split("\n")).strip()
if line:
    with (sinks / f"{label}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
PY
  chmod 755 "$1"
}

# The experiment itself. Rendered by a JSON writer rather than a heredoc: the
# matchers carry `|`, `^` and `$`, and a document Codex cannot load would cost a
# whole run before anyone noticed.
render_hooks_json() {
  local handler="$1" sinks="$2"
  shift 2
  local label matcher
  for label in "$@"; do
    matcher="$(matcher_for "$label")"
    printf '%s\t%s\n' "$label" "$matcher"
  done | python3 -c '
import json, sys

groups = []
handler, sinks = sys.argv[1], sys.argv[2]
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    label, _, matcher = line.partition("\t")
    group = {}
    # Omitted, never emitted empty: an empty string was never observed, and the
    # observed form that fires on every tool call is the one with no key at all.
    if matcher:
        group["matcher"] = matcher
    group["hooks"] = [
        {"type": "command", "command": f"python3 {handler} {label} {sinks}"}
    ]
    groups.append(group)

print(json.dumps({
    "description": "codex-evidence matcher probe — one PreToolUse group per spelling",
    "hooks": {"PreToolUse": groups},
}, indent=2))
' "$handler" "$sinks"
}

# ---------------------------------------------------------------------------
# --dry-run — render the experiment, spawn nothing
# ---------------------------------------------------------------------------

if [ "$DRY_RUN" -eq 1 ]; then
  mkdir -p "$OUT"
  write_handler "$HANDLER"
  echo "probe output: $OUT"
  echo "handler:      $HANDLER"
  echo "sinks:        $SINKS"
  echo
  echo "turn 1 of 2 — shell: a command the model runs through its shell tool"
  echo "turn 2 of 2 — edit:  a single-file change through its native edit tool"
  echo
  echo "hooks.json that would be installed into a throwaway CODEX_HOME:"
  render_hooks_json "$HANDLER" "$SINKS" "${LABELS[@]}"
  exit 0
fi

# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

command -v "$BIN" >/dev/null 2>&1 || { echo "no '$BIN' on PATH" >&2; exit 2; }
[ -f "$REAL_AUTH" ] || {
  echo "no auth at $REAL_AUTH — run 'codex login' first, or set CODEX_AUTH" >&2
  exit 2
}

TIMEOUT_BIN=""
for candidate in timeout gtimeout; do
  if command -v "$candidate" >/dev/null 2>&1; then TIMEOUT_BIN="$candidate"; break; fi
done

run_with_timeout() {
  if [ -n "$TIMEOUT_BIN" ]; then
    "$TIMEOUT_BIN" "$TIMEOUT_SECONDS" "$@"
  else
    "$@"
  fi
}

mkdir -p "$OUT" "$SINKS"
write_handler "$HANDLER"

SCRATCH_HOME="$(mktemp -d)"
SCRATCH_DIRS+=("$SCRATCH_HOME")
# `cp` preserves the source mode. Narrowed explicitly rather than trusted to it:
# a credential is the one file worth being wrong about in the safe direction,
# and `mktemp -d` guarantees the directory, not the file inside it.
cp "$REAL_AUTH" "$SCRATCH_HOME/auth.json"
chmod 600 "$SCRATCH_HOME/auth.json"
render_hooks_json "$HANDLER" "$SINKS" "${LABELS[@]}" > "$SCRATCH_HOME/hooks.json"
export CODEX_HOME="$SCRATCH_HOME"

echo "probe output: $OUT"
echo "binary:       $("$BIN" --version 2>&1 | head -1)"
echo "timeout:      ${TIMEOUT_BIN:-none available — a stalled turn will hang}"
echo "codex home:   $SCRATCH_HOME  (throwaway; removed on exit)"
echo

echo "== rendered PreToolUse groups =="
python3 - "$SCRATCH_HOME/hooks.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
for index, group in enumerate(doc["hooks"]["PreToolUse"]):
    print(f"  {index} · matcher={group.get('matcher', '<none>')!r}")
PY
echo

# One turn. The workspace is fresh per turn so the second cannot read the first's
# result off disk, and the sinks are rotated into a per-turn directory afterwards
# — which needs no cooperation from the handler, so a handler that never ran
# leaves no file at all. That absence is the finding.
drive_turn() {
  local turn="$1" prompt="$2"
  local work exit_code=0

  work="$(mktemp -d)"
  SCRATCH_DIRS+=("$work")
  ( cd "$work" && git init -q )
  printf 'first line\nsecond line\n' > "$work/target.txt"
  ( cd "$work" && git add -A && git commit -q -m seed )

  echo "-- turn: $turn"
  run_with_timeout "$BIN" exec \
    --dangerously-bypass-hook-trust \
    --sandbox workspace-write \
    --skip-git-repo-check \
    -C "$work" \
    --json \
    "$prompt" \
    > "$OUT/stream-$turn.jsonl" 2> "$OUT/stream-$turn.stderr" || exit_code=$?

  echo "   exit=$exit_code  target.txt changed: $(
    if grep -q '^FIRST LINE$' "$work/target.txt" 2>/dev/null; then echo yes; else echo no; fi
  )"

  mv "$SINKS" "$OUT/turn-$turn"
  mkdir -p "$SINKS"
  python3 "$SUMMARY" "$OUT/turn-$turn" "$(IFS=,; echo "${LABELS[*]}")" | sed 's/^/   /'
  echo
}

echo "== per-spelling readings =="
echo

# Probe 1's prompt, which measured a `Bash` shell call on this binary.
drive_turn shell \
  "Run exactly this shell command and nothing else, then stop: printf 'probe\\n'. \
Do not create, read or modify any file, and do not ask me anything."

# Probe 4c's prompt, which measured `tool_name: apply_patch` on this binary.
drive_turn edit \
  "Use your native file-edit tool (not a shell command) to change 'first line' \
to 'FIRST LINE' in target.txt. Make exactly one edit, then stop."

cat <<EOF
== done ==

Artifacts under: $OUT

The throwaway CODEX_HOME — holding a copy of your auth.json — was removed on
exit, as were both workspaces. The sinks and the JSONL streams under \$OUT were
NOT: they are the deliverable. Delete the directory once you have pasted the two
tables:

  rm -rf $OUT

READING THE TABLES. \`none\` is the control and is the LAST group.

  * \`none\` fires and nothing else does  ->  H3: no PreToolUse matcher matches
    under Codex, in any spelling tried. Every matcher the harness deploys for
    this event is a silently suppressed hook.
  * \`bare-bash\` fires on the shell turn and \`alt-claude\` does not  ->  H1:
    the matcher is honoured but the alternation syntax is not. The eight groups
    the harness deploys today are suppressed because of their SPELLING.
  * a spelling fires and the shipped hook still allowed the call in F9  ->  H2:
    the group fires and the hook answers allow. That is a blocking hook failing
    open, and the fix is in the hook, not the matcher.
  * \`apply-patch\` or \`shell\` fires where the Claude Code names do not  ->
    the native names are the matcher's vocabulary, and the adapter must
    translate operations to them rather than forward Claude Code's literals.

Paste both tables into specs/designs/codex-evidence.md as Probe 5 under §4,
dated, and correct the two rows there that this run contradicts.
EOF
