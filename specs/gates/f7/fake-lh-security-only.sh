#!/usr/bin/env bash
# Control shim for isolation-gate.sh — the MUST-FAIL half of the both-directions
# check. Emulates a build in which ONLY pre-tool-use-security honours the
# invoking profile; every other migrated hook still resolves globally and leaks
# into $CLAUDE_CONFIG_DIR. The gate must catch that and exit 1.
#
#   EXPECTED VERDICT: FAIL (exit 1)
#
# Run it (F7_GATE_PYTHON is required: this shim is a shell script with no
# interpreter beside it, and the gate derives its hook lists from the registry):
#
#   F7_GATE_PYTHON=/path/to/venv/bin/python3 \
#     ./isolation-gate.sh "$PWD/fake-lh-security-only.sh"; echo "exit=$?"
#
# Its opposite number is fake-lh-fixed.sh, which must exit 0.
exec env F7_FAKE_FIXED=pre-tool-use-security "$(dirname "${BASH_SOURCE[0]}")/fake-lh.sh" "$@"
