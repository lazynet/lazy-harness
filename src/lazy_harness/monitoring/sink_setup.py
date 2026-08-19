"""Turn `MetricsConfig` + a `MetricsDB` into a list of instantiated sinks.

Built-in sinks are resolved here directly (not via the registry) because
they live in the same repo and their constructor signatures are known.
The registry is consulted only for entry-point (`ext:*`) sinks, which is
wired in a later task if needed for the MVP of this slice.

This module is also where `url_env` is resolved. Reading the variable here
rather than in the config parser keeps the endpoint (which may carry a token
in its path) out of `Config`, and therefore out of anything `save_config`
writes back to disk.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lazy_harness.core.config import MetricsConfig
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.monitoring.sinks.sqlite_local import SqliteLocalSink

_BUILTIN_NAMES = frozenset({"sqlite_local", "http_remote"})


@dataclass(frozen=True)
class SinkPlan:
    """What a configured sink resolves to for this run.

    `active` false means the sink is configured but its endpoint is not
    available — the run proceeds without it. Callers that report to the user
    (`lh doctor`, `lh metrics ingest`) read `url_env` to name the variable
    they were looking for.
    """

    name: str
    active: bool
    url: str = ""
    url_env: str = ""


def _resolve_remote(name: str, options: dict[str, Any], env: Mapping[str, str]) -> tuple[str, str]:
    """Return `(url, url_env)` for a remote sink; url empty means inactive.

    The parser has already rejected `url` and `url_env` together, so at most
    one of them is set here.
    """
    url_env = options.get("url_env", "")
    if isinstance(url_env, str) and url_env:
        return env.get(url_env, "").strip(), url_env
    url = options.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError(f"{name} sink requires a non-empty 'url' or 'url_env' option")
    return url, ""


def plan_sinks(cfg: MetricsConfig, *, env: Mapping[str, str] | None = None) -> list[SinkPlan]:
    """Resolve every configured sink to an activation decision.

    Raises ValueError for a remote sink that names its endpoint neither way.
    An unset variable is not that case: it deactivates the sink instead, so a
    user who never sets it keeps running local-only with no config edit.
    """
    environ = os.environ if env is None else env
    plans: list[SinkPlan] = []
    for name in cfg.sinks:
        definition = cfg.sink_configs.get(name)
        options = definition.options if definition else {}
        if name == "sqlite_local":
            plans.append(SinkPlan(name=name, active=True))
            continue
        url, url_env = _resolve_remote(name, options, environ)
        plans.append(SinkPlan(name=name, active=bool(url), url=url, url_env=url_env))
    return plans


def build_sinks(
    cfg: MetricsConfig, *, db: MetricsDB, env: Mapping[str, str] | None = None
) -> list[Any]:
    for name in cfg.sinks:
        if name not in _BUILTIN_NAMES:
            raise ValueError(
                f"unknown built-in sink: {name!r} (extension sinks TBD in a later slice)"
            )

    sinks: list[Any] = []
    for plan in plan_sinks(cfg, env=env):
        if not plan.active:
            continue
        definition = cfg.sink_configs.get(plan.name)
        options = definition.options if definition else {}
        if plan.name == "sqlite_local":
            sinks.append(SqliteLocalSink(db=db))
        else:
            sinks.append(
                HttpRemoteSink(
                    db=db,
                    url=plan.url,
                    timeout_seconds=float(options.get("timeout_seconds", 5.0)),
                    batch_size=int(options.get("batch_size", 50)),
                )
            )
    return sinks
