"""Cross-platform path resolution for lazy-harness.

Resolution order for each directory:
1. Explicit env var (LH_CONFIG_DIR, LH_DATA_DIR, LH_CACHE_DIR)
2. XDG env vars (XDG_CONFIG_HOME, etc.) — Linux/macOS
3. Platform defaults:
   - macOS/Linux: ~/.config, ~/.local/share, ~/.cache
   - Windows: %APPDATA%, %LOCALAPPDATA%
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

APP_NAME = "lazy-harness"


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE", os.environ.get("HOME", Path.home())))


def config_dir() -> Path:
    """Return the config directory for lazy-harness."""
    explicit = os.environ.get("LH_CONFIG_DIR")
    if explicit:
        return Path(explicit)

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME

    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", _home() / "AppData" / "Roaming")
        return Path(appdata) / APP_NAME

    return _home() / ".config" / APP_NAME


def data_dir() -> Path:
    """Return the data directory for lazy-harness."""
    explicit = os.environ.get("LH_DATA_DIR")
    if explicit:
        return Path(explicit)

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME

    if platform.system() == "Windows":
        local = os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local")
        return Path(local) / APP_NAME

    return _home() / ".local" / "share" / APP_NAME


def cache_dir() -> Path:
    """Return the cache directory for lazy-harness."""
    explicit = os.environ.get("LH_CACHE_DIR")
    if explicit:
        return Path(explicit)

    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / APP_NAME

    if platform.system() == "Windows":
        local = os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local")
        return Path(local) / APP_NAME / "cache"

    return _home() / ".cache" / APP_NAME


def config_file() -> Path:
    """Return the path to config.toml."""
    return config_dir() / "config.toml"


def expand_path(path: str | Path) -> Path:
    """Expand ~ and resolve to absolute path."""
    return Path(os.path.expanduser(str(path))).resolve()


def contract_path(path: Path | str) -> str:
    """Contract absolute path replacing home dir with ~."""
    s = str(path)
    home = str(_home())
    if s.startswith(home):
        return "~" + s[len(home) :]
    return s
