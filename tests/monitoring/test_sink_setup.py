from pathlib import Path

import pytest

from lazy_harness.core.config import MetricsConfig, SinkDefinition
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sink_setup import build_sinks
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.monitoring.sinks.sqlite_local import SqliteLocalSink


def test_default_metrics_config_yields_only_sqlite_local(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        sinks = build_sinks(MetricsConfig(), db=db)
        assert [type(s).__name__ for s in sinks] == ["SqliteLocalSink"]
    finally:
        db.close()


def test_http_remote_requires_url(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        cfg = MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={"http_remote": SinkDefinition(options={})},
        )
        with pytest.raises(ValueError) as info:
            build_sinks(cfg, db=db)
        assert "url" in str(info.value)
    finally:
        db.close()


def test_http_remote_instantiated_with_options(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        cfg = MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={
                "http_remote": SinkDefinition(
                    options={"url": "https://x.invalid/", "timeout_seconds": 3, "batch_size": 25}
                )
            },
        )
        sinks = build_sinks(cfg, db=db)
        assert isinstance(sinks[0], SqliteLocalSink)
        assert isinstance(sinks[1], HttpRemoteSink)
        assert sinks[1].url == "https://x.invalid/"
    finally:
        db.close()
