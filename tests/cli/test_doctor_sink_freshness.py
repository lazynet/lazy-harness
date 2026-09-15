"""Integration tests for the `Sink freshness` block in `lh doctor`.

Mirrors tests/cli/test_doctor_engram_persist.py.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli import doctor_cmd
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


# --- delivery health: the drain, not the ingest ---

# An instant far enough from any real clock that a test which reads the wall
# clock instead of this one renders a visibly different age rather than a
# plausible one.
_FROZEN_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

_CFG = (
    '[harness]\nversion = "1"\n'
    "[monitoring]\nenabled = true\n"
    'db = "{db}"\n'
    "[metrics]\n"
    'sinks = ["sqlite_local", "http_remote"]\n'
    "[metrics.sink_options.http_remote]\n"
    'url = "https://metrics.flex.internal/ingest"\n'
)


def _enqueue_failing(
    db_path: Path,
    *,
    attempts: int,
    error: str = "HTTP 503",
    created_ts: float | None = None,
) -> None:
    """A row enqueued moments ago that the drain keeps refusing to deliver.

    `created_ts` pins the enqueue instant. A test asserting on the seconds
    bucket of the rendered age has to pin both ends of the subtraction:
    `_fmt_age` truncates, so leaving `created_ts` at wall-clock time makes the
    assertion a budget on how long `lh doctor` takes to reach the age.
    """
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        for _ in range(attempts):
            db.outbox_mark_failed("http_remote", "e1", error=error, retry_after_seconds=60)
        if created_ts is not None:
            db._conn.execute(
                "UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'e1'",
                (created_ts,),
            )
            db._conn.commit()
    finally:
        db.close()


def _enqueue_stalled(db_path: Path, *, oldest_age_seconds: float) -> None:
    """A queue whose head never clears, with nothing having ever failed.

    Ingest keeps enqueuing and every POST succeeds, so both of the older
    signals — enqueue age and failed attempts — stay green.
    """
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="old", payload_json="{}")
        db.outbox_enqueue(sink_name="http_remote", event_id="fresh", payload_json="{}")
        db._conn.execute(
            "UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'old'",
            (time.time() - oldest_age_seconds,),
        )
        db._conn.commit()
    finally:
        db.close()


def test_doctor_fails_on_a_stalled_queue_even_though_nothing_ever_failed(
    tmp_path: Path, monkeypatch
) -> None:
    """The blind spot that let six days of metrics go missing under all-green.

    Enqueue age was minutes and failed attempts were zero, so `lh doctor`
    printed nothing at all while the head of the outbox had been undelivered
    since the previous week. Reporting the count without the age would still
    be useless here: "0 failed attempts" names no problem.
    """
    db_path = tmp_path / "m.db"
    _enqueue_stalled(db_path, oldest_age_seconds=6 * 86400)
    (tmp_path / "config.toml").write_text(_CFG.format(db=db_path.as_posix()))
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(doctor)
    assert "2 undelivered" in result.output
    assert "oldest 6d ago" in result.output
    assert result.exit_code == 1


def test_doctor_stays_silent_about_delivery_until_the_drain_actually_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """The row here is enqueued and untried, which is where every healthy run
    sits between ingest and drain. A line per run would be noise."""
    db_path = tmp_path / "m.db"
    _enqueue_stale(db_path, "http_remote", age_seconds=300)
    (tmp_path / "config.toml").write_text(_CFG.format(db=db_path.as_posix()))
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(doctor)
    assert "Sink freshness" in result.output
    assert "undelivered" not in result.output
    assert result.exit_code == 0


def test_doctor_reports_the_backlog_and_its_last_error(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "m.db"
    _enqueue_failing(db_path, attempts=3)
    (tmp_path / "config.toml").write_text(_CFG.format(db=db_path.as_posix()))
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(doctor)
    assert "1 undelivered" in result.output
    assert "3 failed attempts" in result.output
    assert "HTTP 503" in result.output


def test_doctor_fails_when_the_drain_has_given_up_though_ingest_looks_healthy(
    tmp_path: Path, monkeypatch
) -> None:
    """The gap this closes: the row was enqueued seconds ago, so enqueue age is
    green, and every event is still sitting on the machine.

    Both ends of the age subtraction are pinned to `_FROZEN_NOW`. Reading the
    wall clock for either one turns "0s ago" into a stopwatch on `lh doctor`
    itself: the age is a plain elapsed difference and `_fmt_age` truncates it,
    so the assertion held only while setup plus half of the command finished
    inside one second — measured at 0.48s used of that budget on an idle
    machine, and it tipped over on a loaded one.
    """
    db_path = tmp_path / "m.db"
    _enqueue_failing(db_path, attempts=6, created_ts=_FROZEN_NOW.timestamp())
    (tmp_path / "config.toml").write_text(_CFG.format(db=db_path.as_posix()))
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(doctor_cmd, "_now", lambda: _FROZEN_NOW)

    result = CliRunner().invoke(doctor)
    assert "last enqueued 0s ago" in result.output
    assert result.exit_code == 1


def test_doctor_does_not_fail_on_a_backlog_the_drain_has_only_warned_about(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "m.db"
    _enqueue_failing(db_path, attempts=3)
    (tmp_path / "config.toml").write_text(_CFG.format(db=db_path.as_posix()))
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(doctor)
    assert result.exit_code == 0
