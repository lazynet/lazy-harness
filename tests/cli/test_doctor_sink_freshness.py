"""Integration tests for the `Sink freshness` block in `lh doctor`.

Mirrors tests/cli/test_doctor_engram_persist.py.
"""

from __future__ import annotations

import time
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.doctor_cmd import doctor
from lazy_harness.monitoring.db import MetricsDB


def _enqueue_stale(db_path: Path, sink_name: str, *, age_seconds: float) -> None:
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name=sink_name, event_id="e1", payload_json="{}")
        db._conn.execute(
            "UPDATE sink_outbox SET created_ts = ? WHERE sink_name = ? AND event_id = 'e1'",
            (time.time() - age_seconds, sink_name),
        )
        db._conn.commit()
    finally:
        db.close()


def test_doctor_omits_sink_freshness_when_no_active_remote_sinks(
    tmp_path: Path, monkeypatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "Sink freshness" not in result.output
    assert result.exit_code == 0


def test_doctor_omits_sink_freshness_when_monitoring_disabled(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "m.db"
    _enqueue_stale(db_path, "http_remote", age_seconds=10 * 86400)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url = "https://metrics.flex.internal/ingest"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "Sink freshness" not in result.output
    assert result.exit_code == 0


def test_doctor_omits_sink_freshness_for_an_inactive_sink(tmp_path: Path, monkeypatch) -> None:
    """A never-configured / not-yet-activated sink must never read as stale."""
    db_path = tmp_path / "m.db"
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url_env = "LH_METRICS_URL"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("LH_METRICS_URL", raising=False)

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "Sink freshness" not in result.output
    assert result.exit_code == 0


def test_doctor_reports_ok_for_a_recently_enqueued_sink(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "m.db"
    _enqueue_stale(db_path, "http_remote", age_seconds=300)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url = "https://metrics.flex.internal/ingest/s3cr3t"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "Sink freshness" in result.output
    assert "http_remote" in result.output
    assert result.exit_code == 0


def test_doctor_degrades_but_does_not_fail_at_24h_stale(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "m.db"
    _enqueue_stale(db_path, "http_remote", age_seconds=25 * 3600)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url = "https://metrics.flex.internal/ingest"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "Sink freshness" in result.output
    assert result.exit_code == 0


def test_doctor_fails_when_a_sink_has_been_silent_for_a_week(tmp_path: Path, monkeypatch) -> None:
    """The actual incident: a sink stuck silent for days must flip doctor's exit code."""
    db_path = tmp_path / "m.db"
    _enqueue_stale(db_path, "http_remote", age_seconds=8 * 86400)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url = "https://metrics.flex.internal/ingest"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "Sink freshness" in result.output
    assert result.exit_code == 1


def test_doctor_never_prints_the_sink_url_unredacted(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "m.db"
    _enqueue_stale(db_path, "http_remote", age_seconds=8 * 86400)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url_env = "LH_METRICS_URL"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LH_METRICS_URL", "https://metrics.invalid/ingest/s3cr3t-token")

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "Sink freshness" in result.output
    assert "s3cr3t-token" not in result.output


def test_doctor_reports_missing_for_a_sink_with_no_history(tmp_path: Path, monkeypatch) -> None:
    """DB exists (sqlite_local wrote to it) but http_remote never has: not stale, just new."""
    db_path = tmp_path / "m.db"
    _enqueue_stale(db_path, "sqlite_local", age_seconds=8 * 86400)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url = "https://metrics.flex.internal/ingest"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "Sink freshness" in result.output
    assert result.exit_code == 0


def test_doctor_default_smoke_no_config_at_all_still_passes(tmp_path: Path, monkeypatch) -> None:
    """Parameter-less path: no [metrics]/[monitoring] block, no DB file anywhere."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert result.exit_code == 0
    assert "Sink freshness" not in result.output
    assert not (tmp_path / "data" / "metrics.db").exists()
