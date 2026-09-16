#!/usr/bin/env bash
# Control shim — the MUST-PASS half of the both-directions check.
#
# Emulates today's CodexAdapter from the outside: a stub that maps `Bash ->
# RUN_COMMAND` and nothing else, and builds no `edits`/`reads`. It must
# reproduce the checked-in inert set exactly.
#
#   EXPECTED VERDICT: PASS (exit 0)
#
# It agrees with real-translate.sh by construction, and that is the point: it
# proves the STUB MECHANISM is faithful, which is what makes the two must-fail
# shims' failures attributable to the mapping they change rather than to the
# fact that they are stubs at all.
#
#   F8_GATE_PYTHON=/path/to/.venv/bin/python3 \
#     ./translation-gate.sh "$PWD/fake-translate-bash-only.sh"; echo "exit=$?"
set -euo pipefail
exec "${F8_GATE_PYTHON:?F8_GATE_PYTHON must be set}" \
  "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/translate.py" --codex-map bash
