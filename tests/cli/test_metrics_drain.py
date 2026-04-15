from pathlib import Path

from click.testing import CliRunner
from pytest_httpserver import HTTPServer

from lazy_harness.cli.metrics_cmd import metrics
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent


def _mk_event() -> MetricEvent:
    return MetricEvent(
        event_id="eid-1",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="martin",
        tenant_id="local",
        profile="personal",
        session="s1",
        model="sonnet",
        project="lazy-harness",
        date="2026-04-14",
        input_tokens=100,
        output_tokens=50,
        cache_read=0,
        cache_create=0,
        cost=0.001,
    )


def test_drain_exits_zero_with_nothing_pending(
    tmp_path: Path, monkeypatch, httpserver: HTTPServer
) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{(tmp_path / "m.db").as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        f'url = "{httpserver.url_for("/ingest")}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    httpserver.expect_request("/ingest", method="POST").respond_with_json({"ok": True})

    runner = CliRunner()
    result = runner.invoke(metrics, ["drain"])
    assert result.exit_code == 0
    assert "0 sent" in result.output or "nothing to drain" in result.output


def test_drain_flushes_pending_events(
    tmp_path: Path, monkeypatch, httpserver: HTTPServer
) -> None:
    cfg_path = tmp_path / "config.toml"
    db_path = tmp_path / "m.db"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        f'url = "{httpserver.url_for("/ingest")}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    db = MetricsDB(db_path)
    sink = HttpRemoteSink(
        db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
    )
    sink.write(_mk_event())
    db.close()

    httpserver.expect_request("/ingest", method="POST").respond_with_json({"ok": True})
    runner = CliRunner()
    result = runner.invoke(metrics, ["drain"])
    assert result.exit_code == 0
    assert "1 sent" in result.output
