"""UserPromptSubmit hook: record whether non-trivial work declares a goal.

Ships as a sensor. Injection is gated behind `[loops] inject_goal_prompt`,
which stays false until a baseline exists — see the phase 0 rationale in
specs/designs/2026-08-16-loop-engineering-design.md.

Fail-soft: every path exits 0. A hook that raises takes down the chain.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

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


def _read_stdin_json() -> dict[str, object]:
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _db_path() -> Path:
    from lazy_harness.monitoring.db import resolve_db_path

    return resolve_db_path()


def _injection_enabled() -> bool:
    try:
        from lazy_harness.core.config import load_config
        from lazy_harness.core.paths import config_file

        return bool(load_config(config_file()).loops.inject_goal_prompt)
    except Exception:
        return False


_INJECTION_TEXT = (
    "Antes de ejecutar: declará el criterio de éxito verificable de esta tarea "
    "(qué comando o comprobación demuestra que está hecha), o usá /goal para fijarlo."
)


def _emit_injection() -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": _INJECTION_TEXT,
                }
            }
        )
    )


def main() -> None:
    try:
        payload = _read_stdin_json()
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not is_non_trivial(prompt):
            sys.exit(0)

        session = payload.get("session_id")
        cwd = payload.get("cwd")
        from lazy_harness.monitoring.db import MetricsDB

        MetricsDB(_db_path()).record_loop_event(
            session=session if isinstance(session, str) else "",
            kind="goal_absent",
            project=cwd if isinstance(cwd, str) else "",
        )

        if _injection_enabled():
            _emit_injection()
    except Exception:
        # A hook must degrade, never crash the chain: any failure here (bad
        # payload shape, an unwritable metrics store) is swallowed so the
        # session continues uninterrupted.
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
