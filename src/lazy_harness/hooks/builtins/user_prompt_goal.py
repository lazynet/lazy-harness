"""UserPromptSubmit hook: record whether non-trivial work declares a goal.

Ships as a sensor. Injection is gated behind `[loops] inject_goal_prompt`,
which stays false until a baseline exists — see the phase 0 rationale in
specs/designs/2026-08-16-loop-engineering-design.md.

Fail-soft: every path exits 0. A hook that raises takes down the chain.
"""

from __future__ import annotations

import re

_ACTION_VERBS = frozenset(
    {
        "add",
        "agregá",
        "agrega",
        "arreglá",
        "arregla",
        "build",
        "cableá",
        "cablea",
        "cambiá",
        "cambia",
        "create",
        "escribí",
        "escribe",
        "fix",
        "hacé",
        "hace",
        "implement",
        "implementá",
        "implementa",
        "migrate",
        "migrá",
        "move",
        "refactor",
        "refactorizá",
        "remove",
        "rename",
        "sacá",
        "saca",
        "wire",
    }
)

_FILE_RE = re.compile(r"\b[\w./-]+\.(py|md|toml|yaml|yml|json|sh|lock)\b")
_MIN_CHARS = 25


def is_non_trivial(prompt: str) -> bool:
    """True when the prompt reads like a unit of work rather than a remark.

    Two independent signals, either sufficient: a file reference, or an
    action verb in a prompt long enough to carry a request. Length alone is
    deliberately not a signal — pasted logs and long questions are not work.
    """
    text = prompt.strip()
    if not text:
        return False
    if _FILE_RE.search(text):
        return True
    if len(text) < _MIN_CHARS:
        return False
    words = {word.strip(".,;:!?¿¡\"'()").lower() for word in text.split()}
    return bool(words & _ACTION_VERBS)
