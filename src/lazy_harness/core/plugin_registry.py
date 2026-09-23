"""Claude Code plugin registry paths that no longer resolve.

Claude Code stores absolute paths in `plugins/known_marketplaces.json`
(`installLocation`) and `plugins/installed_plugins.json` (`installPath`). A path
recorded through the old `~/.claude -> <profile>` link names a directory that
vanishes with the link, and Claude Code then refuses every plugin of that
marketplace with `cache-miss` — no error surfaces in the session, the skills are
just absent. The data is still in the profile, under the same relative path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

MARKETPLACES_FILE = "known_marketplaces.json"
INSTALLED_FILE = "installed_plugins.json"
REGISTRY_FILES = (Path("plugins") / MARKETPLACES_FILE, Path("plugins") / INSTALLED_FILE)
# The deploy, the snapshot and the doctor all ask this, so they cannot disagree
# about which profiles carry a registry.
REGISTRY_AGENT = "claude-code"


@dataclass(frozen=True)
class PluginPathDrift:
    registry: Path
    entry: str
    stale: Path
    repair: Path | None


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _in_profile(stale: Path, plugins_dir: Path) -> Path | None:
    """The same path relative to the profile's own `plugins/` dir, if it exists."""
    parts = stale.parts
    if "plugins" not in parts:
        return None
    index = len(parts) - 1 - parts[::-1].index("plugins")
    candidate = plugins_dir.joinpath(*parts[index + 1 :])
    return candidate if candidate.exists() else None


def _slots(config_dir: Path) -> list[tuple[Path, dict, str, dict, str]]:
    """Every (registry, document, entry name, holder, key) carrying a path."""
    plugins_dir = config_dir / "plugins"
    slots: list[tuple[Path, dict, str, dict, str]] = []

    marketplaces_path = plugins_dir / MARKETPLACES_FILE
    marketplaces = _load(marketplaces_path)
    if marketplaces is not None:
        for name, entry in marketplaces.items():
            if isinstance(entry, dict) and isinstance(entry.get("installLocation"), str):
                slots.append((marketplaces_path, marketplaces, name, entry, "installLocation"))

    installed_path = plugins_dir / INSTALLED_FILE
    installed = _load(installed_path)
    plugins = installed.get("plugins") if installed is not None else None
    if installed is not None and isinstance(plugins, dict):
        for name, installs in plugins.items():
            if not isinstance(installs, list):
                continue
            for install in installs:
                if isinstance(install, dict) and isinstance(install.get("installPath"), str):
                    slots.append((installed_path, installed, name, install, "installPath"))
    return slots


def _drift(config_dir: Path) -> list[tuple[PluginPathDrift, dict, dict, str]]:
    plugins_dir = config_dir / "plugins"
    found: list[tuple[PluginPathDrift, dict, dict, str]] = []
    for registry, document, name, holder, key in _slots(config_dir):
        stale = Path(holder[key])
        if stale.exists():
            continue
        drift = PluginPathDrift(registry, name, stale, _in_profile(stale, plugins_dir))
        found.append((drift, document, holder, key))
    return found


def find_plugin_path_drift(config_dir: Path) -> list[PluginPathDrift]:
    """Registry paths in this profile that do not exist on disk."""
    return [drift for drift, _, _, _ in _drift(config_dir)]


def repair_plugin_paths(config_dir: Path) -> list[PluginPathDrift]:
    """Repoint each dangling path whose in-profile twin exists; return those."""
    repaired: list[PluginPathDrift] = []
    dirty: dict[Path, dict] = {}
    for drift, document, holder, key in _drift(config_dir):
        if drift.repair is None:
            continue
        holder[key] = str(drift.repair)
        dirty[drift.registry] = document
        repaired.append(drift)
    # Written through the path, not replaced: a registry that is itself a link
    # stays one.
    for registry, document in dirty.items():
        registry.write_text(json.dumps(document, indent=2) + "\n")
    return repaired
