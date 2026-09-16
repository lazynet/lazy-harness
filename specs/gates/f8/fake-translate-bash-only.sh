#!/usr/bin/env bash
# Control shim — the CodexAdapter as it stood before step 9.
#
# A stub that maps `Bash -> RUN_COMMAND` and nothing else, and builds no
# `edits`/`reads`.
#
#   EXPECTED VERDICT: FAIL (exit 1) — and the flip is the finding.
#
# IT USED TO BE THE MUST-PASS HALF, on the reasoning that it "emulates today's
# CodexAdapter from the outside" and therefore had to reproduce the checked-in
# inert set exactly. It did, while today's adapter mapped one tool and the gate
# fed both legs Claude Code's dialect.
#
# Both halves of that changed on 2026-09-16. The Codex leg now carries Codex's
# real edit dialect (`apply_patch`, patch text under `tool_input.command`) and
# the shipped adapter parses it, so four builtins left the inert set. This shim
# no longer emulates the adapter; it emulates the adapter's PREVIOUS STATE, and
# a gate that still passed it would be one that could not tell the two apart.
#
# What it is still good for is the thing it was built for: it is the stub that
# fails by REGRESSION rather than by partial fix, which is what makes
# `fake-translate-operations-only.sh`'s failure attributable to the missing
# parser specifically instead of to stubbing in general.
#
#   F8_GATE_PYTHON=/path/to/.venv/bin/python3 \
#     ./translation-gate.sh "$PWD/fake-translate-bash-only.sh"; echo "exit=$?"
set -euo pipefail
exec "${F8_GATE_PYTHON:?F8_GATE_PYTHON must be set}" \
  "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/translate.py" --codex-map bash
