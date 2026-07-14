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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lazy_harness.agents.base import AgentAdapter

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


def process_exec_path(binary: Path, name: str) -> Path:
    """Resolve the path to exec so the OS-level process name reads `name`.

    On Linux, the kernel derives a process's `comm` (what `ps -o comm=` and
    `/proc/pid/comm` show) from the basename of the *executed file's path*,
    not from argv[0]. To make that basename read `name` while still running
    `binary`, this maintains a stable symlink `<cache_dir>/bin/<name>` ->
    `binary` and returns the symlink path. Falls back to `binary` unchanged
    if symlinks cannot be created (e.g. unsupported filesystem/platform).
    """
    shim_dir = cache_dir() / "bin"
    link = shim_dir / name
    try:
        shim_dir.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() and link.resolve() == binary.resolve():
            return link
        tmp = shim_dir / f".{name}.{os.getpid()}.tmp"
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        tmp.symlink_to(binary)
        os.replace(tmp, link)
    except OSError:
        return binary
    return link


def agent_runtime_dir(agent: AgentAdapter) -> Path:
    """Resolve the agent's runtime config dir: adapter env var, else its global link.

    Resolution order (ADR-032 L3 — never read agent env vars directly):
    1. The adapter's env var (e.g. CLAUDE_CONFIG_DIR), if set and non-empty.
    2. The adapter's global config link (e.g. ~/.claude), if it has one.
    3. ~/.<agent name> as a last resort.
    """
    env_value = os.environ.get(agent.env_var()) if agent.env_var() else None
    if env_value:
        return Path(env_value)
    link = agent.global_config_link()
    if link is not None:
        return link
    return Path.home() / f".{agent.name}"
