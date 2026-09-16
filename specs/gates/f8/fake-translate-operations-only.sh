#!/usr/bin/env bash
# Control shim — "somebody widened the tool map and stopped there".
#
# Every tool name maps to the right Operation; `edits` and `reads` are still
# never built. This is the exact change a reader of `agents/codex.py:92` would
# make on being told the five builtins are inert.
#
#   EXPECTED VERDICT: PASS (exit 0) — and that verdict IS the finding.
#
# THE VERDICT WAS PREDICTED WRONG AND THE MEASUREMENT CORRECTED IT. This shim was
# written expecting exit 1, on the backlog's claim that `post-tool-use-format`
# and `pre-tool-use-read-size` die at the `operation` gate while the other three
# die at `tool.edits` — two mechanisms, so a mapping fix should revive two hooks
# and the gate should fail on their departure from the inert set. It came back
# exit 0: nothing revived. Measured 2026-09-16 by running the hooks, not by
# reading them:
#
#   post_tool_use_format.main() with operation=MODIFY_FILE and edits=()
#     -> target file unchanged: 'x   =    1\n'
#   post_tool_use_format.main() with operation=MODIFY_FILE and edits=(FileEdit,)
#     -> target file formatted:  'x = 1\n'
#
#   pre_tool_use_read_size.main() with operation=READ_FILE and reads=()
#     -> system_message ''
#   pre_tool_use_read_size.main() with operation=READ_FILE and reads=(path,)
#     -> system_message 'WARN: ... is 5000 lines (~6250 tokens) ...'
#
# The operation gate is the FIRST of two gates in those two hooks, not the only
# one: `post_tool_use_format.py:36` iterates `tool.edits` and
# `pre_tool_use_read_size.py:119` iterates `tool.reads`, both after the gate
# opens. So all five inert builtins need the STRUCTURE, and the tool map alone
# revives none of them.
#
# That makes this shim the strongest single piece of evidence for the decision
# this gate was built to defend: a mapping fix is not a fix, and the person who
# ships one gets a green gate that is green for the same reason it was before.
#
#   F8_GATE_PYTHON=/path/to/.venv/bin/python3 \
#     ./translation-gate.sh "$PWD/fake-translate-operations-only.sh"; echo "exit=$?"
set -euo pipefail
exec "${F8_GATE_PYTHON:?F8_GATE_PYTHON must be set}" \
  "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/translate.py" --codex-map operations
