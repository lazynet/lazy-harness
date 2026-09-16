"""The fail-soft seam between the launchers and the `launches` table.

A launch that cannot be counted still has to happen: the instrument is
bookkeeping about a run and must never be the reason the run fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path / "lh"))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data" / "metrics.db"


def test_record_launch_writes_the_row(store: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.launches import record_launch

    record_launch(profile="flex", agent="codex", entry="exec")

    db = MetricsDB(store)
    try:
        assert db.launch_counts() == {("flex", "codex", "exec"): 1}
    finally:
        db.close()


def test_record_launch_stamps_the_shared_host(store: Path) -> None:
    """One hostname answer in one place: the column must agree with the one
    `session_stats` and `MetricEvent` already carry."""
    from lazy_harness.core.identity import resolve_host
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.launches import record_launch

    record_launch(profile="lazy", agent="claude-code", entry="run")

    db = MetricsDB(store)
    try:
        row = db._conn.execute("SELECT host FROM launches").fetchone()
    finally:
        db.close()
    assert row["host"] == resolve_host()


def test_a_broken_store_does_not_propagate(
    store: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import lazy_harness.monitoring.db as db_module
    from lazy_harness.monitoring.launches import record_launch

    def boom(_path: object) -> None:
        raise OSError("disk went away")

    monkeypatch.setattr(db_module, "MetricsDB", boom)

    record_launch(profile="lazy", agent="claude-code", entry="run")

    assert "disk went away" in capsys.readouterr().err


def test_a_rejected_entry_does_not_propagate(
    store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`record_launch` on the DB validates `entry`; a caller passing a third
    spelling is a bug in the harness, never a failed launch."""
    from lazy_harness.monitoring.launches import record_launch

    record_launch(profile="lazy", agent="claude-code", entry="repl")

    assert "repl" in capsys.readouterr().err
