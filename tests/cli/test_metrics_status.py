from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.metrics_cmd import metrics
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent


def _seed(tmp_path: Path) -> Path:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    sink = HttpRemoteSink(db=db, url="https://x.invalid/", timeout_seconds=1, batch_size=10)
    sink.write(
        MetricEvent(
            event_id="e1",
            schema_version=METRIC_EVENT_SCHEMA_VERSION,
            user_id="m",
            tenant_id="local",
            profile="p",
            session="s",
            model="sonnet",
            project="lh",
            date="2026-04-14",
            input_tokens=1,
            output_tokens=1,
            cache_read=0,
            cache_create=0,
            cost=0.0,
        )
    )
    db.close()
    return db_path


def test_status_reports_pending_count(tmp_path: Path, monkeypatch) -> None:
    db_path = _seed(tmp_path)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url = "https://x.invalid/"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(metrics, ["status"])
    assert result.exit_code == 0
    assert "http_remote" in result.output
    assert "pending: 1" in result.output
