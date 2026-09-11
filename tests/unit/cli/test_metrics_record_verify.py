"""Unit tests for `lh metrics record-verify`.

The producer half of the verification loop. `stop-verify-guard` reads a
`verify_ran` event to decide whether a session that declared a goal actually
verified before closing; until this command existed nothing wrote that event,
which is why the guard shipped registered but deliberately unwired.

The tests that matter most are the ones pinning producer and consumer to the
same session key and the same database file — a mismatch there writes an event
nothing reads, with no error and no way to notice.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner


def _invoke(args: list[str], env: dict[str, str] | None = None):
    from lazy_harness.cli.main import cli

    return CliRunner().invoke(cli, ["metrics", *args], env=env or {})


class TestRecordVerify:
    def test_writes_a_verify_ran_event_for_the_named_session(self, tmp_path: Path) -> None:
        from lazy_harness.monitoring.db import MetricsDB

        db_path = tmp_path / "m.db"
        result = _invoke(["record-verify", "--session", "s1", "--db", str(db_path)])

        assert result.exit_code == 0, result.output
        assert MetricsDB(db_path).has_loop_event("s1", "verify_ran") is True

    def test_falls_back_to_the_session_id_in_the_environment(self, tmp_path: Path) -> None:
        """A skill invoking this has no session id to pass; the agent's
        environment carries it."""
        from lazy_harness.monitoring.db import MetricsDB

        db_path = tmp_path / "m.db"
        result = _invoke(
            ["record-verify", "--db", str(db_path)],
            env={"CLAUDE_CODE_SESSION_ID": "from-env"},
        )

        assert result.exit_code == 0, result.output
        assert MetricsDB(db_path).has_loop_event("from-env", "verify_ran") is True

    def test_an_explicit_session_wins_over_the_environment(self, tmp_path: Path) -> None:
        from lazy_harness.monitoring.db import MetricsDB

        db_path = tmp_path / "m.db"
        _invoke(
            ["record-verify", "--session", "explicit", "--db", str(db_path)],
            env={"CLAUDE_CODE_SESSION_ID": "from-env"},
        )

        db = MetricsDB(db_path)
        assert db.has_loop_event("explicit", "verify_ran") is True
        assert db.has_loop_event("from-env", "verify_ran") is False

    def test_fails_loudly_with_no_session_anywhere(self, tmp_path: Path) -> None:
        """Unlike a hook, this is a command a human invokes: silence would
        leave them believing the verification was recorded."""
        result = _invoke(
            ["record-verify", "--db", str(tmp_path / "m.db")],
            env={"CLAUDE_CODE_SESSION_ID": ""},
        )

        assert result.exit_code != 0
        assert "CLAUDE_CODE_SESSION_ID" in result.output

    def test_recording_twice_is_harmless(self, tmp_path: Path) -> None:
        from lazy_harness.monitoring.db import MetricsDB

        db_path = tmp_path / "m.db"
        for _ in range(2):
            assert (
                _invoke(["record-verify", "--session", "s1", "--db", str(db_path)]).exit_code == 0
            )

        assert MetricsDB(db_path).has_loop_event("s1", "verify_ran") is True

    def test_stamps_the_project_key_and_profile(self, tmp_path: Path) -> None:
        """The event has to carry the same dimensions every other loop event
        does, or `lh metrics loops` reports it under a different slice.

        Read back over SQL rather than through the class: the point is what
        landed in the table, not what the writer believes it wrote.
        """
        import sqlite3

        db_path = tmp_path / "m.db"
        _invoke(["record-verify", "--session", "s1", "--db", str(db_path)])

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT kind, project, profile FROM loop_events WHERE session = 's1'"
            ).fetchone()
        finally:
            conn.close()

        assert row is not None, "no event written"
        kind, project, _profile = row
        assert kind == "verify_ran"
        assert project != "", "project key not stamped"

    def test_stamps_the_profile_when_the_agent_env_names_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`profile_name()` degrades to '' when it cannot name a profile, so
        asserting "not empty" against the ambient environment would pass
        trivially in CI while proving nothing.

        A sentinel proves the propagation itself: whatever the helper returns
        is what lands in the row.
        """
        import sqlite3

        from lazy_harness.hooks.builtins import _shared

        monkeypatch.setattr(_shared, "profile_name", lambda: "sentinel-profile")

        db_path = tmp_path / "m.db"
        _invoke(["record-verify", "--session", "s2", "--db", str(db_path)])

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT profile FROM loop_events WHERE session = 's2'").fetchone()
        finally:
            conn.close()

        assert row is not None and row[0] == "sentinel-profile"


class TestProducerAndConsumerAgree:
    """The gate: two paths answering one question must be asserted to agree."""

    def test_the_guard_sees_what_the_command_wrote(self, tmp_path: Path) -> None:
        """End to end across the module boundary, not through a mock.

        This is the assertion that would have caught the whole feature being
        inert: the command writing where the guard does not look.
        """
        from lazy_harness.monitoring.db import MetricsDB

        db_path = tmp_path / "m.db"
        _invoke(["record-verify", "--session", "shared-session", "--db", str(db_path)])

        # Exactly the read the guard performs before deciding to block.
        assert MetricsDB(db_path).has_loop_event("shared-session", "verify_ran") is True

    def test_the_command_and_the_guard_resolve_the_same_default_db(self) -> None:
        """`resolve_db_path` is the one importable answer; anything deriving
        its own copy drifts the moment the config changes."""
        from lazy_harness.cli.metrics_cmd import _resolve_metrics_db
        from lazy_harness.hooks.builtins.stop_verify_guard import _db_path

        assert _resolve_metrics_db(None) == _db_path()

    def test_the_env_var_the_command_reads_is_the_one_claude_code_sets(self) -> None:
        """Pins the identifier itself. A doc naming an env var nothing sets is
        how a mechanism ends up existing only in prose."""
        import inspect

        from lazy_harness.cli import metrics_cmd

        assert "CLAUDE_CODE_SESSION_ID" in inspect.getsource(metrics_cmd)


class TestDbResolution:
    def test_an_explicit_db_wins(self, tmp_path: Path) -> None:
        from lazy_harness.cli.metrics_cmd import _resolve_metrics_db

        explicit = tmp_path / "explicit.db"
        assert _resolve_metrics_db(explicit) == explicit

    def test_without_an_override_it_defers_to_resolve_db_path(self) -> None:
        from lazy_harness.cli.metrics_cmd import _resolve_metrics_db
        from lazy_harness.monitoring.db import resolve_db_path

        assert _resolve_metrics_db(None) == resolve_db_path()

    def test_it_honours_a_configured_db_that_differs_from_the_data_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The negative control for the whole "one importable answer" rule.

        On a default machine `[monitoring] db` and `data_dir()/metrics.db`
        resolve to the same file, so a copy of the resolution logic passes
        every test while being wrong. This configures them apart: anything
        deriving its own path lands in the data dir and fails here.
        """
        from lazy_harness.cli import metrics_cmd
        from lazy_harness.core.paths import data_dir

        elsewhere = tmp_path / "elsewhere" / "metrics.db"
        cfg = tmp_path / "config.toml"
        # `[harness] version` is required; without it load_config raises and
        # resolve_db_path silently falls back — which would make this test
        # pass for the wrong reason.
        cfg.write_text(f'[harness]\nversion = "1"\n\n[monitoring]\ndb = "{elsewhere}"\n')
        monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: cfg)

        resolved = metrics_cmd._resolve_metrics_db(None)

        assert resolved != data_dir() / "metrics.db", "fell back to the data dir"
        assert resolved == elsewhere


@pytest.mark.parametrize("flag", ["--help"])
def test_the_command_is_discoverable(flag: str) -> None:
    result = _invoke(["record-verify", flag])
    assert result.exit_code == 0
    assert "verify" in result.output.lower()
