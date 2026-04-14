"""Turn `MetricsConfig` + a `MetricsDB` into a list of instantiated sinks.

Built-in sinks are resolved here directly (not via the registry) because
they live in the same repo and their constructor signatures are known.
The registry is consulted only for entry-point (`ext:*`) sinks, which is
wired in a later task if needed for the MVP of this slice.
"""

from __future__ import annotations

from typing import Any

from lazy_harness.core.config import MetricsConfig
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.monitoring.sinks.sqlite_local import SqliteLocalSink

_BUILTIN_FACTORIES = {
    "sqlite_local": lambda db, options: SqliteLocalSink(db=db),
    "http_remote": lambda db, options: HttpRemoteSink(
        db=db,
        url=_require_url(options),
        timeout_seconds=float(options.get("timeout_seconds", 5.0)),
        batch_size=int(options.get("batch_size", 50)),
    ),
}


def _require_url(options: dict[str, Any]) -> str:
    url = options.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("http_remote sink requires a non-empty 'url' option")
    return url


def build_sinks(cfg: MetricsConfig, *, db: MetricsDB) -> list[Any]:
    sinks: list[Any] = []
    for name in cfg.sinks:
        factory = _BUILTIN_FACTORIES.get(name)
        if factory is None:
            raise ValueError(
                f"unknown built-in sink: {name!r} (extension sinks TBD in a later slice)"
            )
        definition = cfg.sink_configs.get(name)
        options = definition.options if definition else {}
        sinks.append(factory(db, options))
    return sinks
