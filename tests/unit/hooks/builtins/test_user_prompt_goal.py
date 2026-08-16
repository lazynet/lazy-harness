"""Tests for the UserPromptSubmit goal hook."""

from __future__ import annotations

import io
import json
from pathlib import Path

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


def _run(monkeypatch, payload: object, capsys) -> str:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_records_nontrivial_prompt_for_non_trivial_work(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "prompt": "implementá el hook y agregá el test", "cwd": "/tmp"},
        capsys,
    )

    assert out == "", "the sensor phase must stay silent"
    assert MetricsDB(db_path).loop_event_counts() == {"nontrivial_prompt": 1}


def test_records_nothing_for_a_trivial_prompt(monkeypatch, tmp_path: Path, capsys) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)

    _run(monkeypatch, {"session_id": "s1", "prompt": "gracias", "cwd": "/tmp"}, capsys)

    assert MetricsDB(db_path).loop_event_counts() == {}


@pytest.mark.parametrize("prompt", [None, 42, ["a"], {"nested": "dict"}])
def test_exits_zero_on_valid_json_wrong_type(monkeypatch, tmp_path, capsys, prompt) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)

    _run(monkeypatch, {"session_id": "s1", "prompt": prompt, "cwd": "/tmp"}, capsys)

    assert MetricsDB(db_path).loop_event_counts() == {}


def test_guard_short_circuits_before_is_non_trivial_for_wrong_type_prompt(
    monkeypatch, tmp_path, capsys
) -> None:
    """Prove the isinstance guard prevents `is_non_trivial` from ever being called.

    A test that only checks `sys.exit(0)` cannot tell a correctly guarded
    `main()` apart from one that calls `is_non_trivial(None)` directly, lets
    it raise on `.strip()`, and has the broad `except Exception` swallow the
    crash into the same observable exit code. So this monkeypatches
    `is_non_trivial` to record whether it was invoked at all, and asserts on
    that record rather than on the exit code.
    """
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    calls: list[object] = []

    def _boom(prompt: object) -> bool:
        calls.append(prompt)
        raise AssertionError("is_non_trivial must not be called for a non-str prompt")

    monkeypatch.setattr(mod, "is_non_trivial", _boom)
    monkeypatch.setattr(mod, "_db_path", lambda: tmp_path / "m.db")

    _run(monkeypatch, {"session_id": "s1", "prompt": None, "cwd": "/tmp"}, capsys)

    assert calls == [], "is_non_trivial was reached despite the non-str prompt"


def test_exits_zero_on_malformed_json(monkeypatch, tmp_path, capsys) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr(mod, "_db_path", lambda: tmp_path / "m.db")
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json at all"))

    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 0


def test_exits_zero_when_the_database_is_unwritable(monkeypatch, tmp_path, capsys) -> None:
    """A broken metrics store must never take down the session."""
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("x")
    monkeypatch.setattr(mod, "_db_path", lambda: blocked / "m.db")

    _run(monkeypatch, {"session_id": "s1", "prompt": "fix db.py", "cwd": "/tmp"}, capsys)


def test_injects_only_when_the_flag_is_on(monkeypatch, tmp_path, capsys) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr(mod, "_db_path", lambda: tmp_path / "m.db")
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "prompt": "implementá el hook y agregá el test", "cwd": "/tmp"},
        capsys,
    )

    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "criterio" in payload["hookSpecificOutput"]["additionalContext"].lower()


def test_stays_silent_when_the_flag_is_off(monkeypatch, tmp_path, capsys) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr(mod, "_db_path", lambda: tmp_path / "m.db")
    monkeypatch.setattr(mod, "_injection_enabled", lambda: False)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "prompt": "implementá el hook y agregá el test", "cwd": "/tmp"},
        capsys,
    )

    assert out == ""


def test_injection_enabled_returns_false_when_config_read_fails(monkeypatch) -> None:
    """An unreadable or missing config must never crash the hook; stay silent."""
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    def _boom() -> Path:
        raise OSError("config unreadable")

    monkeypatch.setattr("lazy_harness.core.paths.config_file", _boom)

    assert mod._injection_enabled() is False
