"""TOML config loading, validation, and persistence.

Config lives at ~/.config/lazy-harness/config.toml (or LH_CONFIG_DIR override).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w


class ConfigError(Exception):
    """Raised when config is invalid or missing."""


@dataclass
class ProfileEntry:
    config_dir: str = ""
    roots: list[str] = field(default_factory=list)
    lazynorth_doc: str = ""


@dataclass
class ProfilesConfig:
    default: str = "personal"
    items: dict[str, ProfileEntry] = field(default_factory=dict)


@dataclass
class AgentConfig:
    type: str = "claude-code"


@dataclass
class HarnessConfig:
    version: str = "1"


@dataclass
class KnowledgeSessionsConfig:
    enabled: bool = False
    subdir: str = "sessions"


@dataclass
class KnowledgeLearningsConfig:
    enabled: bool = False
    subdir: str = "learnings"


@dataclass
class KnowledgeSearchConfig:
    engine: str = "qmd"


@dataclass
class KnowledgeConfig:
    path: str = ""
    sessions: KnowledgeSessionsConfig = field(default_factory=KnowledgeSessionsConfig)
    learnings: KnowledgeLearningsConfig = field(default_factory=KnowledgeLearningsConfig)
    search: KnowledgeSearchConfig = field(default_factory=KnowledgeSearchConfig)


@dataclass
class MonitoringConfig:
    enabled: bool = False
    db: str = ""
    pricing: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class SchedulerJobConfig:
    name: str
    schedule: str
    command: str


@dataclass
class SchedulerConfig:
    backend: str = "auto"
    jobs: list[SchedulerJobConfig] = field(default_factory=list)


@dataclass
class HookEventConfig:
    scripts: list[str] = field(default_factory=list)


@dataclass
class LazyNorthConfig:
    enabled: bool = False
    path: str = ""
    universal_doc: str = "LazyNorth.md"


@dataclass
class ContextInjectConfig:
    enabled: bool = True
    max_body_chars: int = 3000
    last_session_enabled: bool = True


@dataclass
class CompoundLoopConfig:
    enabled: bool = False
    model: str = "claude-haiku-4-5-20251001"
    min_messages: int = 4
    min_user_chars: int = 200
    debounce_seconds: int = 60
    timeout_seconds: int = 120
    learnings_subdir: str = "learnings"
    reprocess_min_growth_seconds: int = 120
    grading_enabled: bool = True
    lazymind_dir: str | None = None


@dataclass
class SinkDefinition:
    """Options for a named sink as declared under [metrics.sink_options.<name>]."""

    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricsConfig:
    """Top-level [metrics] block.

    Default (no block): only `sqlite_local` runs, zero network I/O.
    Any other sink requires being named in `sinks` AND having a
    `[metrics.sink_options.<name>]` options block. Missing options block for a
    named sink is a hard error.
    """

    sinks: list[str] = field(default_factory=lambda: ["sqlite_local"])
    sink_configs: dict[str, SinkDefinition] = field(default_factory=dict)
    user_id: str = ""
    tenant_id: str = "local"
    pending_ttl_days: int | None = None


@dataclass
class Config:
    harness: HarnessConfig = field(default_factory=HarnessConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    profiles: ProfilesConfig = field(default_factory=ProfilesConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    hooks: dict[str, HookEventConfig] = field(default_factory=dict)
    compound_loop: CompoundLoopConfig = field(default_factory=CompoundLoopConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    lazynorth: LazyNorthConfig = field(default_factory=LazyNorthConfig)
    context_inject: ContextInjectConfig = field(default_factory=ContextInjectConfig)


def _parse_profiles(raw: dict[str, Any]) -> ProfilesConfig:
    """Parse [profiles] section, separating 'default' key from profile entries."""
    default = raw.get("default", "personal")
    items: dict[str, ProfileEntry] = {}
    for key, value in raw.items():
        if key == "default":
            continue
        if isinstance(value, dict):
            items[key] = ProfileEntry(
                config_dir=value.get("config_dir", ""),
                roots=value.get("roots", []),
                lazynorth_doc=value.get("lazynorth_doc", ""),
            )
    return ProfilesConfig(default=default, items=items)


def _parse_metrics(raw: dict[str, Any]) -> MetricsConfig:
    """Parse [metrics] with the default-local + opt-in-doble invariants.

    Shape:
        [metrics]
        sinks = ["sqlite_local", "http_remote"]
        user_id = "..."
        tenant_id = "..."
        pending_ttl_days = 30

        [metrics.sink_options.http_remote]
        url = "..."

    Rules:
    - Empty/missing [metrics] => sinks=["sqlite_local"], nothing else.
    - A sink named in `sinks` other than `sqlite_local` REQUIRES a
      corresponding `[metrics.sink_options.<name>]` table, else ConfigError.
    - A `[metrics.sink_options.<name>]` block whose name is not in `sinks`
      is silently ignored (dead config).
    """
    if not raw:
        return MetricsConfig()

    sinks = raw.get("sinks", ["sqlite_local"])
    if not isinstance(sinks, list) or not all(isinstance(s, str) and s for s in sinks):
        raise ConfigError("[metrics].sinks must be a list of non-empty strings")

    options_raw = raw.get("sink_options", {})
    if not isinstance(options_raw, dict):
        raise ConfigError("[metrics.sink_options] must be a table")

    sink_configs: dict[str, SinkDefinition] = {}
    for name in sinks:
        if name == "sqlite_local":
            sink_configs[name] = SinkDefinition(options={})
            continue
        if name not in options_raw:
            raise ConfigError(
                f"[metrics] sink {name!r} is named in `sinks` but has no "
                f"[metrics.sink_options.{name}] block"
            )
        block = options_raw[name]
        if not isinstance(block, dict):
            raise ConfigError(f"[metrics.sink_options.{name}] must be a table")
        sink_configs[name] = SinkDefinition(options=dict(block))

    user_id = raw.get("user_id", "")
    if not isinstance(user_id, str):
        raise ConfigError("[metrics].user_id must be a string")
    tenant_id = raw.get("tenant_id", "local")
    if not isinstance(tenant_id, str):
        raise ConfigError("[metrics].tenant_id must be a string")
    ttl = raw.get("pending_ttl_days", None)
    if ttl is not None and not isinstance(ttl, int):
        raise ConfigError("[metrics].pending_ttl_days must be an integer or absent")

    return MetricsConfig(
        sinks=list(sinks),
        sink_configs=sink_configs,
        user_id=user_id,
        tenant_id=tenant_id,
        pending_ttl_days=ttl,
    )


def load_config(path: Path) -> Config:
    """Load and validate config from a TOML file."""
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Failed to parse {path}: {e}") from e

    harness_raw = raw.get("harness", {})
    if not harness_raw.get("version"):
        raise ConfigError(f"Missing [harness].version in {path}")

    cfg = Config()
    cfg.harness = HarnessConfig(version=harness_raw["version"])

    agent_raw = raw.get("agent", {})
    cfg.agent = AgentConfig(type=agent_raw.get("type", "claude-code"))

    profiles_raw = raw.get("profiles", {})
    cfg.profiles = _parse_profiles(profiles_raw)

    knowledge_raw = raw.get("knowledge", {})
    cfg.knowledge = KnowledgeConfig(
        path=knowledge_raw.get("path", ""),
        sessions=KnowledgeSessionsConfig(**knowledge_raw.get("sessions", {})),
        learnings=KnowledgeLearningsConfig(**knowledge_raw.get("learnings", {})),
        search=KnowledgeSearchConfig(**knowledge_raw.get("search", {})),
    )

    monitoring_raw = raw.get("monitoring", {})
    cfg.monitoring = MonitoringConfig(
        enabled=monitoring_raw.get("enabled", False),
        db=monitoring_raw.get("db", ""),
        pricing=monitoring_raw.get("pricing", {}),
    )

    scheduler_raw = raw.get("scheduler", {})
    jobs_raw = scheduler_raw.get("jobs", {})
    jobs: list[SchedulerJobConfig] = []
    if isinstance(jobs_raw, dict):
        for job_name, job_cfg in jobs_raw.items():
            if not isinstance(job_cfg, dict):
                continue
            schedule = job_cfg.get("schedule", "")
            command = job_cfg.get("command", "")
            if not schedule or not command:
                raise ConfigError(f"[scheduler.jobs.{job_name}] missing schedule or command")
            jobs.append(SchedulerJobConfig(name=job_name, schedule=schedule, command=command))
    cfg.scheduler = SchedulerConfig(
        backend=scheduler_raw.get("backend", "auto"),
        jobs=jobs,
    )

    hooks_raw = raw.get("hooks", {})
    for event_name, event_cfg in hooks_raw.items():
        if isinstance(event_cfg, dict):
            cfg.hooks[event_name] = HookEventConfig(
                scripts=event_cfg.get("scripts", []),
            )

    cl_raw = raw.get("compound_loop", {})
    if isinstance(cl_raw, dict):
        cfg.compound_loop = CompoundLoopConfig(
            enabled=cl_raw.get("enabled", False),
            model=cl_raw.get("model", CompoundLoopConfig.model),
            min_messages=cl_raw.get("min_messages", CompoundLoopConfig.min_messages),
            min_user_chars=cl_raw.get("min_user_chars", CompoundLoopConfig.min_user_chars),
            debounce_seconds=cl_raw.get("debounce_seconds", CompoundLoopConfig.debounce_seconds),
            timeout_seconds=cl_raw.get("timeout_seconds", CompoundLoopConfig.timeout_seconds),
            learnings_subdir=cl_raw.get("learnings_subdir", CompoundLoopConfig.learnings_subdir),
            reprocess_min_growth_seconds=cl_raw.get(
                "reprocess_min_growth_seconds",
                CompoundLoopConfig.reprocess_min_growth_seconds,
            ),
            grading_enabled=cl_raw.get("grading_enabled", CompoundLoopConfig.grading_enabled),
            lazymind_dir=cl_raw.get("lazymind_dir", CompoundLoopConfig.lazymind_dir),
        )

    metrics_raw = raw.get("metrics", {})
    cfg.metrics = _parse_metrics(metrics_raw)

    ln_raw = raw.get("lazynorth", {})
    if isinstance(ln_raw, dict):
        cfg.lazynorth = LazyNorthConfig(
            enabled=ln_raw.get("enabled", False),
            path=ln_raw.get("path", ""),
            universal_doc=ln_raw.get("universal_doc", LazyNorthConfig.universal_doc),
        )

    ci_raw = raw.get("context_inject", {})
    if isinstance(ci_raw, dict):
        cfg.context_inject = ContextInjectConfig(
            enabled=ci_raw.get("enabled", True),
            max_body_chars=ci_raw.get("max_body_chars", ContextInjectConfig.max_body_chars),
            last_session_enabled=ci_raw.get(
                "last_session_enabled", ContextInjectConfig.last_session_enabled
            ),
        )

    return cfg


def _config_to_dict(cfg: Config) -> dict[str, Any]:
    """Serialize Config to a dict suitable for TOML output."""
    profiles_dict: dict[str, Any] = {"default": cfg.profiles.default}
    for name, entry in cfg.profiles.items.items():
        profiles_dict[name] = {
            "config_dir": entry.config_dir,
            "roots": entry.roots,
        }

    result: dict[str, Any] = {
        "harness": {"version": cfg.harness.version},
        "agent": {"type": cfg.agent.type},
        "profiles": profiles_dict,
        "knowledge": {
            "path": cfg.knowledge.path,
            "sessions": {
                "enabled": cfg.knowledge.sessions.enabled,
                "subdir": cfg.knowledge.sessions.subdir,
            },
            "learnings": {
                "enabled": cfg.knowledge.learnings.enabled,
                "subdir": cfg.knowledge.learnings.subdir,
            },
            "search": {"engine": cfg.knowledge.search.engine},
        },
        "monitoring": {
            "enabled": cfg.monitoring.enabled,
        },
        "scheduler": {"backend": cfg.scheduler.backend},
    }

    if cfg.monitoring.db:
        result["monitoring"]["db"] = cfg.monitoring.db
    if cfg.monitoring.pricing:
        result["monitoring"]["pricing"] = cfg.monitoring.pricing

    if cfg.hooks:
        hooks_dict: dict[str, Any] = {}
        for event_name, event_cfg in cfg.hooks.items():
            hooks_dict[event_name] = {"scripts": event_cfg.scripts}
        result["hooks"] = hooks_dict

    if (
        cfg.metrics.sinks != ["sqlite_local"]
        or cfg.metrics.user_id
        or cfg.metrics.tenant_id != "local"
        or cfg.metrics.pending_ttl_days is not None
    ):
        metrics_out: dict[str, Any] = {"sinks": cfg.metrics.sinks}
        if cfg.metrics.user_id:
            metrics_out["user_id"] = cfg.metrics.user_id
        if cfg.metrics.tenant_id != "local":
            metrics_out["tenant_id"] = cfg.metrics.tenant_id
        if cfg.metrics.pending_ttl_days is not None:
            metrics_out["pending_ttl_days"] = cfg.metrics.pending_ttl_days
        options: dict[str, Any] = {}
        for name, definition in cfg.metrics.sink_configs.items():
            if name == "sqlite_local":
                continue
            options[name] = definition.options
        if options:
            metrics_out["sink_options"] = options
        result["metrics"] = metrics_out

    return result


def save_config(cfg: Config, path: Path) -> None:
    """Save config to a TOML file."""
    data = _config_to_dict(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tomli_w.dumps(data).encode())
