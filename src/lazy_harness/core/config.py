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
class SchedulerConfig:
    backend: str = "auto"


@dataclass
class Config:
    harness: HarnessConfig = field(default_factory=HarnessConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    profiles: ProfilesConfig = field(default_factory=ProfilesConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)


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
            )
    return ProfilesConfig(default=default, items=items)


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
    cfg.scheduler = SchedulerConfig(backend=scheduler_raw.get("backend", "auto"))

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

    return result


def save_config(cfg: Config, path: Path) -> None:
    """Save config to a TOML file."""
    data = _config_to_dict(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tomli_w.dumps(data).encode())
