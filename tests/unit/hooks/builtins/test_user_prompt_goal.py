"""Tests for the UserPromptSubmit goal hook."""

from __future__ import annotations

import pytest

from lazy_harness.hooks.builtins.user_prompt_goal import is_non_trivial


@pytest.mark.parametrize(
    "prompt",
    [
        "arreglá el bug de canonicalización en compound_loop.py y agregá el test",
        "implement the loop_events table and wire it into metrics_cmd",
        "refactor the ingest path so it stops reading the whole transcript",
    ],
)
def test_treats_substantial_work_requests_as_non_trivial(prompt: str) -> None:
    assert is_non_trivial(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "gracias",
        "sí",
        "que hora es?",
        "y eso por qué?",
    ],
)
def test_treats_short_conversational_turns_as_trivial(prompt: str) -> None:
    assert is_non_trivial(prompt) is False


def test_a_long_prompt_without_an_action_verb_is_trivial() -> None:
    """Length alone must not trigger: pasted logs and questions are long too."""
    prompt = "no entiendo por qué " + "el output dice eso " * 20
    assert is_non_trivial(prompt) is False


def test_a_short_prompt_naming_a_file_is_non_trivial() -> None:
    assert is_non_trivial("fix db.py") is True


def test_empty_and_whitespace_prompts_are_trivial() -> None:
    assert is_non_trivial("") is False
    assert is_non_trivial("   \n  ") is False
