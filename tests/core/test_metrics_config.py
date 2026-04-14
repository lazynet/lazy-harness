"""Tests for the [metrics] config block."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import (
    ConfigError,
    MetricsConfig,
    SinkDefinition,
    load_config,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_absent_metrics_block_defaults_to_sqlite_local_only(tmp_path: Path) -> None:
    cfg_path = _write(tmp_path, '[harness]\nversion = "1"\n')
    cfg = load_config(cfg_path)
    assert isinstance(cfg.metrics, MetricsConfig)
    assert cfg.metrics.sinks == ["sqlite_local"]
    assert cfg.metrics.sink_configs == {}
    assert cfg.metrics.user_id == ""
    assert cfg.metrics.tenant_id == "local"
    assert cfg.metrics.pending_ttl_days is None


def test_named_sink_requires_config_block(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n',
    )
    with pytest.raises(ConfigError) as info:
        load_config(cfg_path)
    assert "http_remote" in str(info.value)


def test_config_block_without_being_named_is_ignored(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url = "https://example.invalid/ingest"\n',
    )
    cfg = load_config(cfg_path)
    assert cfg.metrics.sinks == ["sqlite_local"]
    assert "http_remote" not in cfg.metrics.sink_configs


def test_full_opt_in_parses_cleanly(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        'user_id = "martin-flex"\n'
        'tenant_id = "flex"\n'
        "pending_ttl_days = 30\n"
        "[metrics.sink_options.http_remote]\n"
        'url = "https://example.invalid/ingest"\n'
        "timeout_seconds = 5\n"
        "batch_size = 50\n",
    )
    cfg = load_config(cfg_path)
    assert cfg.metrics.sinks == ["sqlite_local", "http_remote"]
    assert cfg.metrics.user_id == "martin-flex"
    assert cfg.metrics.tenant_id == "flex"
    assert cfg.metrics.pending_ttl_days == 30
    remote = cfg.metrics.sink_configs["http_remote"]
    assert isinstance(remote, SinkDefinition)
    assert remote.options == {
        "url": "https://example.invalid/ingest",
        "timeout_seconds": 5,
        "batch_size": 50,
    }


def test_sqlite_local_is_always_valid_without_config_block(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local"]\n',
    )
    cfg = load_config(cfg_path)
    assert cfg.metrics.sinks == ["sqlite_local"]
