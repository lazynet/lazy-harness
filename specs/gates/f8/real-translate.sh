#!/usr/bin/env bash
# The SUBJECT of translation-gate.sh: the two adapters the harness actually
# ships. `--codex-map real` means `CodexAdapter.parse_hook_input`, untouched.
#
#   EXPECTED VERDICT: PASS (exit 0)
#
# This is the gate's default translator, so `./translation-gate.sh` with no
# argument measures the real tree. The three fake-translate-*.sh shims beside it
# are the discrimination check and drive the same translate.py with a stubbed
# codex side.
set -euo pipefail
exec "${F8_GATE_PYTHON:?F8_GATE_PYTHON must be set; translation-gate.sh exports it}" \
  "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/translate.py" --codex-map real
