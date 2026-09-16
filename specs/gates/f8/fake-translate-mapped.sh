#!/usr/bin/env bash
# Control shim — the MUST-FAIL half of the both-directions check.
#
# Emulates a Codex adapter that translates CORRECTLY: every tool name mapped to
# its Operation, and `edits`/`reads` built the way ClaudeCodeAdapter builds
# them. Nothing degrades, the computed inert set is EMPTY, and the gate must
# fail against a checked-in expectation naming five.
#
#   EXPECTED VERDICT: FAIL (exit 1)
#
# A gate that cannot fail is not evidence. Its opposite number is
# fake-translate-bash-only.sh, which must exit 0.
#
#   F8_GATE_PYTHON=/path/to/.venv/bin/python3 \
#     ./translation-gate.sh "$PWD/fake-translate-mapped.sh"; echo "exit=$?"
set -euo pipefail
exec "${F8_GATE_PYTHON:?F8_GATE_PYTHON must be set}" \
  "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/translate.py" --codex-map full
