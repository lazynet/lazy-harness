"""Where an adapter says its sessions live, and what that implies.

Every test here exists because the alternative spelling — `config_dir /
(agent.session_dirs().get("sessions") or "projects")` — is wrong in a way that
reads as right: `Path(x) / ""` is `x`, so the fallback hands back the whole
config directory instead of refusing.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from lazy_harness.agents.base import Signal, TranscriptEvent
from lazy_harness.agents.session_paths import (
    TranscriptHealth,
    session_path,
    session_subdir,
    transcript_health,
)


class _Declares:
    """Only the attribute under test. `session_dirs` is duck-typed at every
    call site, so a fake carrying the whole `AgentAdapter` surface would hide
    the one failure mode these tests are for."""

    name = "declares"

    def __init__(self, dirs: dict[str, str]) -> None:
        self._dirs = dirs

    def session_dirs(self) -> dict[str, str]:
        return self._dirs


class _DeclaresNothing:
    """An injected collaborator without the attribute at all."""

    name = "declares-nothing"


class _Reads(_Declares):
    """Satisfies `TranscriptReader`, which is `runtime_checkable`."""

    def locate_sessions(self, config_dir: Path, since: datetime | None) -> Iterator[Path]:
        yield from ()

    def read(self, path: Path) -> Iterator[TranscriptEvent]:
        yield from ()

    def signals(self) -> set[Signal]:
        return {Signal.TOKEN_USAGE}


# --- session_subdir ---------------------------------------------------------


def test_session_subdir_returns_the_declared_name() -> None:
    assert session_subdir(_Declares({"sessions": "projects"}), "sessions") == "projects"


def test_session_subdir_is_empty_when_the_agent_declares_no_such_directory() -> None:
    assert session_subdir(_Declares({"sessions": "sessions", "logs": ""}), "logs") == ""


def test_session_subdir_is_empty_when_the_key_is_absent_entirely() -> None:
    assert session_subdir(_Declares({"sessions": "projects"}), "queue") == ""


def test_session_subdir_is_empty_when_the_collaborator_has_no_session_dirs() -> None:
    assert session_subdir(_DeclaresNothing(), "sessions") == ""


def test_session_subdir_is_empty_when_session_dirs_answers_with_the_wrong_type() -> None:
    class _Wrong:
        def session_dirs(self) -> dict[str, str]:
            return ["projects"]  # type: ignore[return-value]

    assert session_subdir(_Wrong(), "sessions") == ""


# --- session_path -----------------------------------------------------------


def test_session_path_joins_the_declared_subdirectory(tmp_path: Path) -> None:
    got = session_path(_Declares({"sessions": "projects"}), tmp_path, "sessions")
    assert got == tmp_path / "projects"


def test_session_path_refuses_rather_than_returning_the_config_dir(tmp_path: Path) -> None:
    """The `Path(x) / ""` trap: the wrong spelling returns `tmp_path` itself."""
    got = session_path(_Declares({"sessions": ""}), tmp_path, "sessions")
    assert got is None
    assert got != tmp_path


# --- transcript_health ------------------------------------------------------


def test_no_location_is_decided_before_any_file_is_looked_at(tmp_path: Path) -> None:
    """The trap, end to end.

    An adapter declaring nothing, and a config dir holding a real file that is
    not a transcript. The one-liner the design rejects globs `tmp_path` itself,
    finds `settings.json`, and reports degraded.
    """
    (tmp_path / "settings.json").write_text("{}")
    assert transcript_health(_Declares({}), tmp_path) is TranscriptHealth.NO_LOCATION


def test_no_location_when_the_collaborator_has_no_session_dirs(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text("{}")
    assert transcript_health(_DeclaresNothing(), tmp_path) is TranscriptHealth.NO_LOCATION


def test_ok_when_a_reader_has_transcripts_to_read(tmp_path: Path) -> None:
    (tmp_path / "projects" / "a").mkdir(parents=True)
    (tmp_path / "projects" / "a" / "s.jsonl").write_text("{}\n")
    agent = _Reads({"sessions": "projects"})
    assert transcript_health(agent, tmp_path) is TranscriptHealth.OK


def test_degraded_when_transcripts_exist_and_nothing_can_read_them(tmp_path: Path) -> None:
    (tmp_path / "sessions" / "2026" / "09").mkdir(parents=True)
    (tmp_path / "sessions" / "2026" / "09" / "rollout-x.jsonl").write_text("{}\n")
    agent = _Declares({"sessions": "sessions"})
    assert transcript_health(agent, tmp_path) is TranscriptHealth.DEGRADED


def test_no_data_when_the_declared_directory_holds_no_transcripts(tmp_path: Path) -> None:
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "session-store.db").write_text("")
    assert transcript_health(_Declares({"sessions": "sessions"}), tmp_path) is (
        TranscriptHealth.NO_DATA
    )


def test_no_data_when_the_declared_directory_does_not_exist(tmp_path: Path) -> None:
    """Copilot's `history-session-state/`: a location declared and simply wrong.

    Distinct from `NO_LOCATION` on purpose — the agent did answer the question.
    """
    assert transcript_health(_Declares({"sessions": "history-session-state"}), tmp_path) is (
        TranscriptHealth.NO_DATA
    )


def test_a_reader_over_an_empty_directory_is_not_degraded(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()
    assert transcript_health(_Reads({"sessions": "projects"}), tmp_path) is (
        TranscriptHealth.NO_DATA
    )


def test_the_shipped_adapters_answer_the_question_they_are_asked(tmp_path: Path) -> None:
    """Both shipped readers locate data under what `session_dirs()` declares.

    Derived from the registry rather than restated: an adapter added with a
    sessions directory it cannot read is the case this asserts against.
    """
    from lazy_harness.agents.registry import get_agent

    for agent_type, subdir in (("claude-code", "projects"), ("codex", "sessions")):
        agent = get_agent(agent_type)
        assert session_subdir(agent, "sessions") == subdir
        root = tmp_path / agent_type / subdir / "nested"
        root.mkdir(parents=True)
        (root / "rollout-x.jsonl").write_text("{}\n")
        assert transcript_health(agent, tmp_path / agent_type) is TranscriptHealth.OK
