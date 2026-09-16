"""UserPromptSubmit hook: record whether non-trivial work declares a goal.

Ships as a sensor. Injection is gated behind `[loops] inject_goal_prompt`,
which stays false until a baseline exists — see the phase 0 rationale in
specs/designs/2026-08-16-loop-engineering-design.md.

Fail-soft: every path abstains. A hook that raises takes down the chain.
"""

from __future__ import annotations

import re
from pathlib import Path

from lazy_harness.agents.base import HookDecision, HookEvent

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


def main(event: HookEvent) -> HookDecision:
    try:
        prompt = event.prompt
        if not isinstance(prompt, str) or not is_non_trivial(prompt):
            return HookDecision()

        from lazy_harness.hooks.builtins._shared import project_key
        from lazy_harness.monitoring.db import MetricsDB

        # `parse_hook_input` yields `Path("")` -- which is `Path(".")` -- when
        # the payload names no cwd, and `project_key` would resolve that to
        # whatever directory the agent happened to spawn the hook in. This
        # column is a metrics label rather than a path the hook writes to, so
        # an unattributed row beats one attributed to the wrong project.
        MetricsDB(_db_path()).record_loop_event(
            session=event.session_id,
            kind="nontrivial_prompt",
            project=project_key(event.cwd) if event.cwd != Path(".") else "",
            # The profile the command was invoked under, not the one the
            # ambient `CLAUDE_CONFIG_DIR` names: every profile records into a
            # single store, and `profile_name()` answered `""` for every hook
            # run under an explicit `--profile`.
            profile=event.profile,
        )

        if _injection_enabled():
            return HookDecision(additional_context=_INJECTION_TEXT)
    except Exception:
        # A hook must degrade, never crash the chain: any failure here (an
        # unwritable metrics store, a prompt of a shape the adapter let
        # through) is swallowed so the session continues uninterrupted.
        pass
    return HookDecision()
