"""The compound-loop evaluator's prompt head, importable without the worker.

The evaluator runs as a headless agent session, so the prompt hooks fire inside
it like in any other session. A hook that must tell the two apart imports this
module rather than `compound_loop`, whose import cost every prompt would pay.
"""

from __future__ import annotations

EVALUATOR_PROMPT_HEAD = "You are evaluating a Claude Code session for learnings."


def is_evaluator_prompt(text: str) -> bool:
    return text.lstrip().startswith(EVALUATOR_PROMPT_HEAD)
