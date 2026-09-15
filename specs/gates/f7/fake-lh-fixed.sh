#!/usr/bin/env bash
# Control shim for isolation-gate.sh — the MUST-PASS half of the both-directions
# check. Emulates a build in which EVERY hook resolves its evidence dir from the
# invoking profile's config_dir. Nothing leaks, so the gate must exit 0.
#
#   EXPECTED VERDICT: PASS (exit 0)
#
# Run it (F7_GATE_PYTHON is required: this shim is a shell script with no
# interpreter beside it, and the gate derives its hook lists from the registry):
#
#   F7_GATE_PYTHON=/path/to/venv/bin/python3 \
#     ./isolation-gate.sh "$PWD/fake-lh-fixed.sh"; echo "exit=$?"
#
# Its opposite number is fake-lh-security-only.sh, which must exit 1. A gate that
# only ever fails proves nothing; these two are what make it a checker.
exec env F7_FAKE_FIXED=ALL "$(dirname "${BASH_SOURCE[0]}")/fake-lh.sh" "$@"
