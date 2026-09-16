#!/usr/bin/env bash
# Control shim — the MUST-FAIL half of the both-directions check.
#
# Every tool name mapped to its Operation, and `edits`/`reads` built the way
# ClaudeCodeAdapter builds them — from `tool_input.file_path`.
#
#   EXPECTED VERDICT: FAIL (exit 1)
#
# IT NOW FAILS IN BOTH DIRECTIONS, which it did not before 2026-09-16, and the
# reason is worth more than the verdict. `file_path` is Claude Code's field.
# Codex's edit dialect does not have one: the touched path lives inside the
# patch blob under `command`. So reading `file_path` is not "translating
# correctly" any more — it is translating the wrong agent:
#
#   the four edit builtins  became INERT   — no `file_path` in an apply_patch
#                                            payload, so no edits are built
#   pre-tool-use-read-size  stopped being  — the `read_file` leg is still fed
#                           INERT            Claude's synthetic `Read` payload,
#                                            which does carry `file_path`
#
# That is a sharper control than the one it replaced. It used to demonstrate
# only that the gate can fail; it now demonstrates that the gate distinguishes
# a structure built from the RIGHT field from one built from a field the agent
# never sends.
#
#   F8_GATE_PYTHON=/path/to/.venv/bin/python3 \
#     ./translation-gate.sh "$PWD/fake-translate-mapped.sh"; echo "exit=$?"
set -euo pipefail
exec "${F8_GATE_PYTHON:?F8_GATE_PYTHON must be set}" \
  "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/translate.py" --codex-map full
