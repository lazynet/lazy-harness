"""Invariant: a config without [metrics] must not touch the network.

Verified by monkeypatching httpx to raise on any attempted use.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from lazy_harness.core.config import Config
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.ingest import ingest_all
from lazy_harness.monitoring.sink_setup import build_sinks


def test_default_config_has_only_sqlite_local() -> None:
    cfg = Config()
    assert cfg.metrics.sinks == ["sqlite_local"]


def test_default_config_ingest_does_not_use_httpx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class _Boom(httpx.Client):
        def __init__(self, *a, **kw):  # type: ignore[no-untyped-def]
            calls.append("init")
            super().__init__(*a, **kw)

        def post(self, *a, **kw):  # type: ignore[no-untyped-def]
            calls.append("post")
            raise AssertionError("network I/O attempted in local-only mode")

    monkeypatch.setattr(httpx, "Client", _Boom)

    cfg = Config()  # default
    db = MetricsDB(tmp_path / "m.db")
    try:
        sinks = build_sinks(cfg.metrics, db=db)
        ingest_all(cfg, db, pricing={}, sinks=sinks)
    finally:
        db.close()

    assert "post" not in calls  # zero HTTP calls
