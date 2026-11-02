"""The isolation contract of a headless `claude -p`, defined once.

Two argv builders spawn `claude -p`: the evaluator backend (`llm/claude.py`) and
the `lh exec` adapter (`agents/claude_code.py`). Neither layer may import the
other, so the shared part lives here, where both can. Each builder keeps its
deliberate difference (evaluator: no transcript, no tools; exec: transcript kept,
tool guards re-injected). Evidence: `specs/designs/claude-code-evidence.md`.
"""

from __future__ import annotations

HEADLESS_PRINT_FLAG = "-p"

# An empty source list loads no settings file, so no settings or plugin hook
# fires and a headless run is not a user session; OAuth still works, unlike
# `--bare`. The JSON envelope is the only record of what a call spent.
HEADLESS_ISOLATION_FLAGS: tuple[str, ...] = (
    "--output-format",
    "json",
    "--setting-sources",
    "",
)
