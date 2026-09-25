"""Integration tests for the `Launches` block in `lh doctor`.

Mirrors tests/cli/test_doctor_sink_freshness.py: `lh doctor` never creates a
metrics DB that does not already exist, so the smoke test asserts that too.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli import doctor_cmd
from lazy_harness.cli.doctor_cmd import doctor
from lazy_harness.monitoring.db import MetricsDB


def _stat(session: str, date: str, profile: str) -> dict[str, object]:
    return {
        "session": session,
        "date": date,
        "model": "claude-opus-4-6",
        "profile": profile,
        "project": "p",
        "input": 1,
        "output": 1,
        "cache_read": 0,
        "cache_create": 0,
        "cost": 0.0,
    }


def _write_config(tmp_path: Path, db_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        f'[harness]\nversion = "1"\n[monitoring]\nenabled = true\ndb = "{db_path.as_posix()}"\n'
    )


def test_doctor_reports_none_and_never_creates_a_missing_db(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "nonexistent.db"
    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

    result = CliRunner().invoke(doctor)

    assert "Launches" in result.output
    assert "none" in result.output
    assert not db_path.exists()
    assert result.exit_code == 0


def test_doctor_lists_non_claude_profiles_and_shows_horizon_opens_before_it_elapses(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    db.record_launch(profile="flex", agent="codex", entry="exec")
    db.close()
    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

    result = CliRunner().invoke(doctor)

    assert "flex" in result.output
    assert "horizon opens 2026-11-11" in result.output
    assert result.exit_code == 0


def test_doctor_reports_horizon_not_started_when_uncalibrated(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    db.record_launch(profile="flex", agent="codex", entry="exec")
    db.close()
    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 12, 1, tzinfo=UTC))

    result = CliRunner().invoke(doctor)

    assert "horizon not started: launch-to-session ratio unmeasured" in result.output
    assert result.exit_code == 0


def test_doctor_names_the_profile_below_threshold_once_calibrated(
    tmp_path: Path, monkeypatch
) -> None:
    frozen_dt = datetime(2026, 12, 1, 12, tzinfo=UTC)
    monkeypatch.setattr(MetricsDB, "_now", lambda self: frozen_dt.timestamp())

    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    for _ in range(10):
        db.record_launch(profile="lazy", agent="claude-code", entry="run")
    db.insert_stats([_stat(f"s{i}", "2026-11-20", "lazy") for i in range(5)])
    for _ in range(9):
        db.record_launch(profile="flex", agent="codex", entry="exec")
    db.close()

    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: frozen_dt)

    result = CliRunner().invoke(doctor)

    assert "flex" in result.output
    assert "below threshold" in result.output
    assert result.exit_code == 0


def _strip_wal_sidecars(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    for suffix in ("-wal", "-shm"):
        side_car = Path(str(db_path) + suffix)
        if side_car.exists():
            side_car.unlink()


def test_doctor_reads_launches_without_write_access_to_the_metrics_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """`lh doctor` reads an existing, non-WAL metrics DB whose directory it
    cannot write to. The write-path `MetricsDB(path)` constructor fails
    here (needs to create a `-wal` side-car); doctor must not use it."""
    db_dir = tmp_path / "metrics"
    db_dir.mkdir()
    db_path = db_dir / "m.db"
    db = MetricsDB(db_path)
    db.record_launch(profile="flex", agent="codex", entry="exec")
    db.close()
    _strip_wal_sidecars(db_path)

    os.chmod(db_dir, 0o500)
    try:
        with pytest.raises(sqlite3.OperationalError):
            MetricsDB(db_path)

        _write_config(tmp_path, db_path)
        monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

        result = CliRunner().invoke(doctor)

        assert "flex" in result.output
        assert result.exit_code == 0
    finally:
        os.chmod(db_dir, 0o700)


def test_doctor_reports_unreadable_for_a_wal_mode_db_under_a_readonly_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """The realistic steady state: a metrics DB stays in WAL journal mode
    (set once at creation) but every writer closes its own connection, so
    the next open has no `-wal`/`-shm` side-cars to reuse — opening it
    needs to create one even just to read. `lh doctor` reports that as an
    explicit, unverifiable diagnostic rather than reaching for a weaker
    (`immutable=1`) connection that could return stale data as if current;
    the directory being unwritable is not proof of a genuine problem, so
    the exit code stays 0."""
    db_dir = tmp_path / "metrics"
    db_dir.mkdir()
    db_path = db_dir / "m.db"
    db = MetricsDB(db_path)
    db.record_launch(profile="flex", agent="codex", entry="exec")
    db.close()
    assert not Path(str(db_path) + "-wal").exists()

    os.chmod(db_dir, 0o500)
    try:
        _write_config(tmp_path, db_path)
        monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

        result = CliRunner().invoke(doctor)

        assert "unreadable" in result.output
        assert result.exit_code == 0, result.output
    finally:
        os.chmod(db_dir, 0o700)


def test_doctor_reports_unreadable_launches_db_and_still_renders_other_sections(
    tmp_path: Path, monkeypatch
) -> None:
    """An unreadable metrics DB degrades to a structured diagnostic on the
    `Launches` section; the rest of `lh doctor` keeps working."""
    db_path = tmp_path / "m.db"
    MetricsDB(db_path).close()
    os.chmod(db_path, 0o000)
    try:
        _write_config(tmp_path, db_path)
        monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

        result = CliRunner().invoke(doctor)

        assert "Profiles:" in result.output
        assert "Launches" in result.output
        assert "unreadable" in result.output
        assert result.exit_code == 0, result.output
    finally:
        os.chmod(db_path, 0o600)


def test_doctor_fails_on_a_genuinely_broken_launches_db(tmp_path: Path, monkeypatch) -> None:
    """A metrics DB missing its `launches` table entirely (predates the
    table) is a real finding, not an environment limit — doctor exits
    nonzero."""
    db_path = tmp_path / "m.db"
    legacy = sqlite3.connect(str(db_path))
    legacy.execute("CREATE TABLE session_stats (session TEXT)")
    legacy.commit()
    legacy.close()

    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

    result = CliRunner().invoke(doctor)

    assert "unreadable" in result.output
    assert result.exit_code == 1


def test_doctor_json_reports_unreadable_launches_as_structured_diagnostic(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "m.db"
    MetricsDB(db_path).close()
    os.chmod(db_path, 0o000)
    try:
        _write_config(tmp_path, db_path)
        monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

        result = CliRunner().invoke(doctor, ["--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["launches"]["permission_denied"] is True
        assert "reason" in payload["launches"]
        assert "profiles" in payload
    finally:
        os.chmod(db_path, 0o600)


def test_doctor_text_and_json_agree_on_launches_diagnostic(tmp_path: Path, monkeypatch) -> None:
    """One helper backs both renderers, so a genuine (non-permission)
    failure reports the same verdict — and the same nonzero exit code —
    in text and in `--json`. `--json` used to always return before its
    own exit-code logic ran, so this failure mode exited 0 under `--json`
    while text mode correctly failed."""
    db_path = tmp_path / "m.db"
    legacy = sqlite3.connect(str(db_path))
    legacy.execute("CREATE TABLE session_stats (session TEXT)")
    legacy.commit()
    legacy.close()

    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

    text_result = CliRunner().invoke(doctor)
    json_result = CliRunner().invoke(doctor, ["--json"])
    payload = json.loads(json_result.output)

    assert payload["launches"]["permission_denied"] is False
    assert "unreadable" in text_result.output
    assert text_result.exit_code == 1
    assert json_result.exit_code == 1


def test_doctor_json_stays_exit_zero_for_permission_denied_launches(
    tmp_path: Path, monkeypatch
) -> None:
    """The counterpart to the previous test: `--json` exits 0 when the
    launches diagnostic is explicitly `permission_denied` — unverifiable
    is not treated as a genuine failure in either mode."""
    db_path = tmp_path / "m.db"
    MetricsDB(db_path).close()
    os.chmod(db_path, 0o000)
    try:
        _write_config(tmp_path, db_path)
        monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

        json_result = CliRunner().invoke(doctor, ["--json"])

        assert json_result.exit_code == 0, json_result.output
        payload = json.loads(json_result.output)
        assert payload["launches"]["permission_denied"] is True
    finally:
        os.chmod(db_path, 0o600)


def test_doctor_reports_damaged_table_pages_as_unreadable_not_a_crash(
    tmp_path: Path, monkeypatch
) -> None:
    """`sqlite_master` opens fine (so `open_readonly` succeeds) but the
    `launches` table's own pages are corrupt — SQLite raises a plain
    `sqlite3.DatabaseError` here ("database disk image is malformed"),
    not an `OperationalError`; measured to previously propagate
    uncaught and crash `lh doctor` instead of degrading to a diagnostic."""
    db_path = tmp_path / "m.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE launches (ts REAL, profile TEXT, agent TEXT, host TEXT, entry TEXT)")
    for i in range(50):
        conn.execute(
            "INSERT INTO launches VALUES (?, ?, ?, ?, ?)", (i, "flex", "codex", "", "exec")
        )
    conn.commit()
    conn.close()

    data = bytearray(db_path.read_bytes())
    n = len(data)
    for i in range(n // 2, n):
        data[i] = 0xFF
    db_path.write_bytes(bytes(data))

    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

    result = CliRunner().invoke(doctor)

    # A controlled `SystemExit(1)` from the diagnostic path, not an
    # unhandled crash: Click's runner sets `.exception` for either, so the
    # distinguishing check is that stdout is the clean report, never a
    # traceback.
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    assert "Traceback" not in result.output
    assert "Profiles:" in result.output
    assert "unreadable" in result.output
    assert result.exit_code == 1

    json_result = CliRunner().invoke(doctor, ["--json"])
    assert "Traceback" not in json_result.output
    assert json_result.exit_code == 1
    payload = json.loads(json_result.output)
    assert payload["launches"]["permission_denied"] is False


def test_doctor_reports_genuine_failure_when_the_configured_db_path_is_a_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """`monitoring.db` pointing at a directory is a misconfigured path, not
    "no DB created yet" — must report as a genuine failure (exit 1 in both
    text and `--json`), never fall back to an empty, healthy-looking
    store."""
    db_path = tmp_path / "m.db"
    db_path.mkdir()

    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

    result = CliRunner().invoke(doctor)
    assert "unreadable" in result.output
    assert result.exit_code == 1

    json_result = CliRunner().invoke(doctor, ["--json"])
    assert json_result.exit_code == 1
    payload = json.loads(json_result.output)
    assert payload["launches"]["permission_denied"] is False


def test_doctor_banner_stays_all_checks_passed_when_fully_verified(
    tmp_path: Path, monkeypatch
) -> None:
    """The exact, existing banner text is a promise this diff must not
    silently change for a fully-verified run."""
    db_path = tmp_path / "nonexistent.db"
    _write_config(tmp_path, db_path)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

    result = CliRunner().invoke(doctor)

    assert "All checks passed." in result.output
    assert result.exit_code == 0


def test_doctor_banner_is_qualified_not_all_checks_passed_when_launches_is_unverifiable(
    tmp_path: Path, monkeypatch
) -> None:
    """A permission-denied `Launches` read keeps exit 0 (unverifiable is
    not a confirmed failure), but the closing banner must not claim every
    check passed — that would misreport a section this environment could
    not actually check as confirmed healthy."""
    db_path = tmp_path / "m.db"
    MetricsDB(db_path).close()
    os.chmod(db_path, 0o000)
    try:
        _write_config(tmp_path, db_path)
        monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
        monkeypatch.setattr(doctor_cmd, "_now", lambda: datetime(2026, 9, 20, tzinfo=UTC))

        result = CliRunner().invoke(doctor)

        assert result.exit_code == 0, result.output
        assert "All checks passed." not in result.output
        assert "unreadable" in result.output
    finally:
        os.chmod(db_path, 0o600)
