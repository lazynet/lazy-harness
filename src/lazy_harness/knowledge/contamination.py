"""Evaluator prompts that landed in the knowledge store as if they were work.

The compound-loop evaluator is itself a headless agent session, so its prompt
reaches the store through the paths that file ordinary sessions: a slim
`handoff.md` quoting it as the last user prompt, and a session note whose first
user message is it. `lh doctor` counts both so a regression of the guards
cannot stay silent. Only the head of each file is read: the prompt opens the
message, and a file can run to ~90 KB across thousands of session notes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from lazy_harness.knowledge.evaluator_prompt import EVALUATOR_PROMPT_HEAD, is_evaluator_prompt
from lazy_harness.knowledge.marker import MarkerError, read_marker

_HEAD_BYTES = 8192
_FIRST_USER_TURN = "\n## User\n\n"


@dataclass(frozen=True)
class EvaluatorContamination:
    checked: bool
    handoffs: list[Path] = field(default_factory=list)
    sessions: list[Path] = field(default_factory=list)


def _head(path: Path) -> str:
    with path.open("rb") as f:
        return f.read(_HEAD_BYTES).decode("utf-8", errors="replace")


def _handoff_contaminated(path: Path) -> bool:
    return any(line.startswith(EVALUATOR_PROMPT_HEAD) for line in _head(path).splitlines())


def _session_contaminated(path: Path) -> bool:
    text = _head(path)
    _, sep, first_message = text.partition(_FIRST_USER_TURN)
    return bool(sep) and is_evaluator_prompt(first_message)


def _scan(base: Path, pattern: str, contaminated: Callable[[Path], bool]) -> list[Path]:
    found: list[Path] = []
    for path in sorted(base.rglob(pattern)):
        try:
            if path.is_file() and contaminated(path):
                found.append(path)
        except OSError:
            continue
    return found


def collect_evaluator_contamination(root: object) -> EvaluatorContamination:
    """Count contaminated files under the store at `root`.

    `checked` is False when there was nothing to scan (no root, no directory, an
    unreadable marker): the doctor row says so instead of reporting a clean store.
    """
    if not isinstance(root, Path) or not root.is_dir():
        return EvaluatorContamination(checked=False)
    try:
        marker = read_marker(root)
    except MarkerError:
        return EvaluatorContamination(checked=False)
    memory, sessions = root / marker.memory, root / marker.sessions
    return EvaluatorContamination(
        checked=True,
        handoffs=_scan(memory, "handoff.md", _handoff_contaminated) if memory.is_dir() else [],
        sessions=_scan(sessions, "*.md", _session_contaminated) if sessions.is_dir() else [],
    )
