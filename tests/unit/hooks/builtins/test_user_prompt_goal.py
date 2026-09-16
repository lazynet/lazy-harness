"""Tests for the UserPromptSubmit goal hook."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lazy_harness.agents.base import HookDecision, HookEvent
from lazy_harness.hooks.builtins.user_prompt_goal import is_non_trivial

WORK_PROMPT = "implementá el hook y agregá el test"


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


def _event(
    *,
    prompt: object = WORK_PROMPT,
    cwd: str = "/tmp",
    profile: str = "p",
    session_id: str = "s1",
) -> HookEvent:
    """One UserPromptSubmit event.

    `prompt` is typed `object` rather than `str | None` on purpose: the
    dataclass validates nothing at runtime, and the hook's `isinstance` guard
    is what stands between a payload that named a list and a `.strip()` on it.
    A helper that refused to build the wrong shape would make that guard
    untestable.
    """
    return HookEvent(
        event="user_prompt_submit",
        profile=profile,
        session_id=session_id,
        cwd=Path(cwd),
        transcript_path=None,
        prompt=prompt,  # type: ignore[arg-type]
    )


def _run(monkeypatch, event: HookEvent, db_path: Path) -> HookDecision:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    return mod.main(event)


def test_records_nontrivial_prompt_for_non_trivial_work(monkeypatch, tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"

    decision = _run(monkeypatch, _event(), db_path)

    assert decision == HookDecision(), "the sensor phase must stay silent"
    assert MetricsDB(db_path).loop_event_counts() == {"nontrivial_prompt": 1}


def _recorded(db_path: Path) -> list[tuple[str, str]]:
    """(kind, project) per row — `loop_event_counts` groups the column away."""
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT kind, project FROM loop_events").fetchall()


def test_records_the_repo_root_when_launched_from_an_artifact_subdirectory(
    monkeypatch, tmp_path: Path, git_checkout
) -> None:
    """The cwd is not the project: `<repo>/graphify-out` is still `<repo>`.

    Recording the raw cwd split one repo's events across two keys, and no
    test saw it because every assertion went through `loop_event_counts`,
    which groups by kind and discards `project` entirely.
    """
    db_path = tmp_path / "m.db"

    _run(monkeypatch, _event(cwd=str(git_checkout.subdir)), db_path)

    assert _recorded(db_path) == [("nontrivial_prompt", str(git_checkout.repo))]


def test_records_the_main_repo_when_launched_from_a_worktree(
    monkeypatch, tmp_path: Path, git_checkout
) -> None:
    db_path = tmp_path / "m.db"

    _run(monkeypatch, _event(cwd=str(git_checkout.worktree)), db_path)

    assert _recorded(db_path) == [("nontrivial_prompt", str(git_checkout.repo.resolve()))]


def test_records_an_empty_project_when_the_event_names_no_cwd(monkeypatch, tmp_path: Path) -> None:
    """A missing cwd must not resolve against the hook's own process cwd.

    `parse_hook_input` yields `Path("")` — which is `Path(".")`, and truthy —
    when the payload names no cwd, so a hook that handed it straight to
    `project_key` would resolve the directory the agent happened to spawn it
    in and label the row with a project nobody asked about. `session-end`
    takes the same branch for the same reason and for the same column; the
    hooks that encode the cwd into a directory *name* take the opposite one.
    """
    db_path = tmp_path / "m.db"

    _run(monkeypatch, _event(cwd=""), db_path)

    assert _recorded(db_path) == [("nontrivial_prompt", "")]


def test_labels_the_row_with_the_events_profile_not_the_ambient_one(
    monkeypatch, tmp_path: Path, active_profile: str
) -> None:
    """Both profiles share one metrics store; a row must name the invoked one.

    `active_profile` points `CLAUDE_CONFIG_DIR` at the *other* profile, which
    is what `profile_name()` used to read. Passing a third value on the event
    and asserting on it is what makes this fail if that helper comes back — an
    event whose profile merely agreed with the ambient one could not.
    """
    db_path = tmp_path / "m.db"
    assert active_profile != "lazy", "the fixture must name the non-default profile"

    _run(monkeypatch, _event(profile="lazy"), db_path)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT profile FROM loop_events").fetchall() == [("lazy",)]


def test_records_nothing_for_a_trivial_prompt(monkeypatch, tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"

    decision = _run(monkeypatch, _event(prompt="gracias"), db_path)

    assert decision == HookDecision()
    assert MetricsDB(db_path).loop_event_counts() == {}


@pytest.mark.parametrize("prompt", [None, 42, ["a"], {"nested": "dict"}])
def test_abstains_when_the_prompt_is_absent_or_the_wrong_type(
    monkeypatch, tmp_path, prompt
) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"

    decision = _run(monkeypatch, _event(prompt=prompt), db_path)

    assert decision == HookDecision()
    assert MetricsDB(db_path).loop_event_counts() == {}


def test_guard_short_circuits_before_is_non_trivial_for_wrong_type_prompt(
    monkeypatch, tmp_path
) -> None:
    """Prove the isinstance guard prevents `is_non_trivial` from ever being called.

    A test that only checks the abstention cannot tell a correctly guarded
    `main()` apart from one that calls `is_non_trivial(None)` directly, lets
    it raise on `.strip()`, and has the broad `except Exception` swallow the
    crash into the same `HookDecision()`. So this monkeypatches
    `is_non_trivial` to record whether it was invoked at all, and asserts on
    that record rather than on the return value.
    """
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    calls: list[object] = []

    def _boom(prompt: object) -> bool:
        calls.append(prompt)
        raise AssertionError("is_non_trivial must not be called for a non-str prompt")

    monkeypatch.setattr(mod, "is_non_trivial", _boom)

    _run(monkeypatch, _event(prompt=None), tmp_path / "m.db")

    assert calls == [], "is_non_trivial was reached despite the non-str prompt"


def test_abstains_when_the_database_is_unwritable(monkeypatch, tmp_path) -> None:
    """A broken metrics store must never take down the session."""
    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("x")

    decision = _run(monkeypatch, _event(prompt="fix db.py"), blocked / "m.db")

    assert decision == HookDecision()


def test_injects_only_when_the_flag_is_on(monkeypatch, tmp_path) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)

    decision = _run(monkeypatch, _event(), tmp_path / "m.db")

    assert "criterio" in decision.additional_context.lower()
    assert decision.verdict is None, "a sensor must not form a verdict"


def test_stays_silent_when_the_flag_is_off(monkeypatch, tmp_path) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr(mod, "_injection_enabled", lambda: False)

    decision = _run(monkeypatch, _event(), tmp_path / "m.db")

    assert decision.additional_context == ""


def test_injection_enabled_returns_false_when_config_read_fails(monkeypatch) -> None:
    """An unreadable or missing config must never crash the hook; stay silent."""
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    def _boom() -> Path:
        raise OSError("config unreadable")

    monkeypatch.setattr("lazy_harness.core.paths.config_file", _boom)

    assert mod._injection_enabled() is False
