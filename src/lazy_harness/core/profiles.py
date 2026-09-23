"""Profile management — list, add, remove, resolve."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.config import Config, ProfileEntry
from lazy_harness.core.paths import expand_path


class ProfileError(Exception):
    """Raised for profile operation failures."""


@dataclass
class ProfileInfo:
    name: str
    config_dir: Path
    roots: list[str]
    is_default: bool
    exists: bool


def list_profiles(cfg: Config) -> list[ProfileInfo]:
    """Return info about all configured profiles."""
    result: list[ProfileInfo] = []
    for name, entry in cfg.profiles.items.items():
        config_path = expand_path(entry.config_dir)
        result.append(
            ProfileInfo(
                name=name,
                config_dir=config_path,
                roots=entry.roots,
                is_default=(name == cfg.profiles.default),
                exists=config_path.is_dir(),
            )
        )
    return result


def add_profile(cfg: Config, name: str, config_dir: str, roots: list[str]) -> None:
    """Add a new profile to config."""
    if name in cfg.profiles.items:
        raise ProfileError(f"Profile '{name}' already exists")
    cfg.profiles.items[name] = ProfileEntry(config_dir=config_dir, roots=roots)


def remove_profile(cfg: Config, name: str) -> None:
    """Remove a profile from config."""
    if name not in cfg.profiles.items:
        raise ProfileError(f"Profile '{name}' not found")
    if name == cfg.profiles.default:
        raise ProfileError(f"Cannot remove default profile '{name}'. Change default first.")
    del cfg.profiles.items[name]


SOURCE_EXPLICIT = "explicit"
SOURCE_ROOT_MATCH = "root-match"
SOURCE_DEFAULT_FALLBACK = "default-fallback"

PROFILE_SOURCES: tuple[str, ...] = (SOURCE_EXPLICIT, SOURCE_ROOT_MATCH, SOURCE_DEFAULT_FALLBACK)
"""How a profile was decided. `default-fallback` means nothing matched the cwd.

Callers that record which profile an invocation ran under need to distinguish a
match from a guess: a cwd outside every configured root resolves to the default
profile, which is correct only for as long as the default happens to be the
right one.
"""


@dataclass(frozen=True)
class ProfileResolution:
    name: str
    source: str


def _profile_agent_prefix(cfg: Config, name: str) -> str:
    from lazy_harness.agents.registry import profile_prefix

    entry = cfg.profiles.items[name]
    return profile_prefix(entry.agent or cfg.agent.type)


def resolve_profile_with_source(
    cfg: Config,
    cwd: Path | None = None,
    override: str | None = None,
    agent: str | None = None,
) -> ProfileResolution:
    """Resolve the profile and report how it was decided.

    Longest matching root wins. An `override` short-circuits the match and is
    validated here so every caller rejects an unknown name the same way.

    `agent` is a profile-prefix (`"claude"`, `"codex"`, `"copilot"`) that
    filters candidates *before* the root loop, and is checked against
    `override` rather than combined with it: a `--profile` naming a different
    agent's profile is a contradiction, not a narrowing.
    """
    if agent is not None:
        from lazy_harness.agents.registry import PROFILE_PREFIXES

        valid = sorted({p for a, p in PROFILE_PREFIXES.items() if a != "null"})
        if agent not in valid:
            raise ProfileError(f"unknown agent {agent!r}; expected one of {', '.join(valid)}")

    if override is not None:
        if override not in cfg.profiles.items:
            raise ProfileError(f"Unknown profile '{override}'")
        if agent is not None and _profile_agent_prefix(cfg, override) != agent:
            raise ProfileError(
                f"--profile {override!r} runs agent "
                f"{_profile_agent_prefix(cfg, override)!r}, not {agent!r}"
            )
        return ProfileResolution(name=override, source=SOURCE_EXPLICIT)

    if cwd is None:
        cwd = Path.cwd()

    candidates = cfg.profiles.items
    if agent is not None:
        candidates = {
            name: entry
            for name, entry in candidates.items()
            if _profile_agent_prefix(cfg, name) == agent
        }

    cwd_str = str(cwd.resolve())
    best_len = 0
    best_matches: list[str] = []

    for name, entry in candidates.items():
        for root in entry.roots:
            root_str = str(expand_path(root))
            if not cwd_str.startswith(root_str):
                continue
            if len(root_str) > best_len:
                best_len = len(root_str)
                best_matches = [name]
            elif len(root_str) == best_len and name not in best_matches:
                best_matches.append(name)

    if not best_matches:
        if agent is None:
            return ProfileResolution(name=cfg.profiles.default, source=SOURCE_DEFAULT_FALLBACK)
        if cfg.profiles.default in candidates:
            return ProfileResolution(name=cfg.profiles.default, source=SOURCE_DEFAULT_FALLBACK)
        if len(candidates) == 1:
            return ProfileResolution(name=next(iter(candidates)), source=SOURCE_DEFAULT_FALLBACK)
        raise ProfileError(f"no {agent} profile claims {cwd}; pass --profile")

    if len(best_matches) == 1:
        return ProfileResolution(name=best_matches[0], source=SOURCE_ROOT_MATCH)

    # Design decision 7 (2026-09-13 multi-agent blast radius design): two or
    # more profiles claim the same root, and `len(root_str) > best_len` above
    # is strictly-greater, so picking one here would be picking by TOML
    # document order — invisible in the output and silent in the launch. The
    # tie is refused instead, unless exactly one claimant declares
    # `root_default` (the loader guarantees at most one, see
    # `_validate_root_defaults`).
    defaulters = [name for name in best_matches if cfg.profiles.items[name].root_default]
    if len(defaulters) == 1:
        return ProfileResolution(name=defaulters[0], source=SOURCE_ROOT_MATCH)

    raise ProfileError(
        f"root claimed by {', '.join(best_matches)} has no default profile; "
        f"pass --profile, or set root_default = true on one of them"
    )


def resolve_profile(cfg: Config, cwd: Path | None = None) -> str:
    """Resolve which profile to use based on cwd. Longest matching root wins."""
    return resolve_profile_with_source(cfg, cwd).name


@dataclass(frozen=True)
class SharedRootInfo:
    """One root claimed by two or more profiles — `lh doctor`'s evidence for
    the ambiguity `resolve_profile_with_source` refuses at launch time."""

    root: str
    profiles: list[str]
    agents: dict[str, str]
    default: str | None


def collect_shared_roots(cfg: Config) -> list[SharedRootInfo]:
    """Every root two or more profiles claim, each with its agent and default.

    A root claimed by exactly one profile has nothing to disambiguate and is
    omitted — the same "silent when there is nothing to say" rule the other
    `lh doctor` sections follow.
    """
    from lazy_harness.agents.registry import agent_for_profile

    by_root: dict[str, list[str]] = {}
    for name, entry in cfg.profiles.items.items():
        for root in entry.roots:
            by_root.setdefault(str(expand_path(root)), []).append(name)

    result: list[SharedRootInfo] = []
    for root, names in by_root.items():
        if len(names) < 2:
            continue
        agents = {name: agent_for_profile(cfg, name).name for name in names}
        defaulters = [name for name in names if cfg.profiles.items[name].root_default]
        result.append(
            SharedRootInfo(
                root=root,
                profiles=names,
                agents=agents,
                default=defaulters[0] if len(defaulters) == 1 else None,
            )
        )
    return result


def root_routing_is_configured(cfg: Config) -> bool:
    """True when at least one profile declares a root, i.e. cwd routing is in use.

    With no roots anywhere, resolving to the default profile is the configured
    design rather than a guess, so it is not worth warning about. `lh init`
    leaves exactly that state until the user adds roots.
    """
    return any(entry.roots for entry in cfg.profiles.items.values())
