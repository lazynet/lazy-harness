from pathlib import Path

import pytest

from lazy_harness.core.config import MetricsConfig, SinkDefinition
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sink_setup import build_sinks, plan_sinks
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


def test_url_env_set_activates_http_remote_with_the_resolved_url(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LH_METRICS_URL", "https://metrics.invalid/ingest/tok")
    db = MetricsDB(tmp_path / "m.db")
    try:
        cfg = MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={"http_remote": SinkDefinition(options={"url_env": "LH_METRICS_URL"})},
        )
        sinks = build_sinks(cfg, db=db)
        assert [type(s).__name__ for s in sinks] == ["SqliteLocalSink", "HttpRemoteSink"]
        assert sinks[1].url == "https://metrics.invalid/ingest/tok"
    finally:
        db.close()


def test_url_env_unset_deactivates_http_remote_without_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LH_METRICS_URL", raising=False)
    db = MetricsDB(tmp_path / "m.db")
    try:
        cfg = MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={"http_remote": SinkDefinition(options={"url_env": "LH_METRICS_URL"})},
        )
        sinks = build_sinks(cfg, db=db)
        assert [type(s).__name__ for s in sinks] == ["SqliteLocalSink"]
    finally:
        db.close()


def test_url_env_set_but_empty_deactivates_http_remote(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LH_METRICS_URL", "   ")
    db = MetricsDB(tmp_path / "m.db")
    try:
        cfg = MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={"http_remote": SinkDefinition(options={"url_env": "LH_METRICS_URL"})},
        )
        sinks = build_sinks(cfg, db=db)
        assert [type(s).__name__ for s in sinks] == ["SqliteLocalSink"]
    finally:
        db.close()


def test_plan_names_the_variable_when_the_sink_is_inactive(monkeypatch) -> None:
    monkeypatch.delenv("LH_METRICS_URL", raising=False)
    cfg = MetricsConfig(
        sinks=["sqlite_local", "http_remote"],
        sink_configs={"http_remote": SinkDefinition(options={"url_env": "LH_METRICS_URL"})},
    )
    plans = {p.name: p for p in plan_sinks(cfg)}
    assert plans["sqlite_local"].active is True
    remote = plans["http_remote"]
    assert remote.active is False
    assert remote.url_env == "LH_METRICS_URL"
    assert remote.url == ""


def test_plan_reports_an_active_sink_with_its_resolved_url(monkeypatch) -> None:
    monkeypatch.setenv("LH_METRICS_URL", "https://metrics.invalid/ingest/tok")
    cfg = MetricsConfig(
        sinks=["sqlite_local", "http_remote"],
        sink_configs={"http_remote": SinkDefinition(options={"url_env": "LH_METRICS_URL"})},
    )
    remote = {p.name: p for p in plan_sinks(cfg)}["http_remote"]
    assert remote.active is True
    assert remote.url == "https://metrics.invalid/ingest/tok"
    assert remote.url_env == "LH_METRICS_URL"


def test_plan_reports_a_url_configured_sink_with_no_variable() -> None:
    cfg = MetricsConfig(
        sinks=["sqlite_local", "http_remote"],
        sink_configs={"http_remote": SinkDefinition(options={"url": "https://x.invalid/"})},
    )
    remote = {p.name: p for p in plan_sinks(cfg)}["http_remote"]
    assert remote.active is True
    assert remote.url == "https://x.invalid/"
    assert remote.url_env == ""


def test_neither_url_nor_url_env_is_an_error() -> None:
    cfg = MetricsConfig(
        sinks=["sqlite_local", "http_remote"],
        sink_configs={"http_remote": SinkDefinition(options={})},
    )
    with pytest.raises(ValueError) as info:
        plan_sinks(cfg)
    assert "url_env" in str(info.value)
