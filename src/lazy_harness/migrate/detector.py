from __future__ import annotations

import shutil
from pathlib import Path

from lazy_harness.core.paths import config_file as default_config_file
from lazy_harness.migrate.state import (
    ClaudeCodeSetup,
    DeployedScript,
    DetectedState,
    LaunchAgentInfo,
    LazyClaudecodeSetup,
)


def detect_claude_code(claude_dir: Path) -> ClaudeCodeSetup | None:
    """Detect a vanilla Claude Code setup at the given directory.

    Returns None if the directory does not exist, is not a directory,
    or contains neither settings.json nor CLAUDE.md.
    """
    if not claude_dir.exists() or not claude_dir.is_dir():
        return None

    has_settings = (claude_dir / "settings.json").is_file()
    has_claude_md = (claude_dir / "CLAUDE.md").is_file()

    if not has_settings and not has_claude_md:
        return None

    return ClaudeCodeSetup(
        path=claude_dir,
        has_settings=has_settings,
        has_claude_md=has_claude_md,
    )


def detect_lazy_claudecode(home: Path) -> LazyClaudecodeSetup | None:
    """Scan home for ~/.claude-<profile>/ directories.

    Returns None if no lazy-claudecode-style profile dirs are found.
    A profile dir must contain a settings.json file to be counted.
    """
    profiles: list[str] = []
    claude_dirs: dict[str, Path] = {}
    skills_dirs: dict[str, Path] = {}
    settings_paths: dict[str, Path] = {}

    if not home.exists():
        return None

    for entry in sorted(home.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if not name.startswith(".claude-"):
            continue
        profile = name[len(".claude-"):]
        if not profile:
            continue

        settings = entry / "settings.json"
        if not settings.is_file():
            continue

        profiles.append(profile)
        claude_dirs[profile] = entry
        settings_paths[profile] = settings
        skills = entry / "skills"
        if skills.is_dir():
            skills_dirs[profile] = skills

    if not profiles:
        return None

    return LazyClaudecodeSetup(
        profiles=profiles,
        claude_dirs=claude_dirs,
        skills_dirs=skills_dirs,
        settings_paths=settings_paths,
    )


def detect_deployed_scripts(bin_dir: Path) -> list[DeployedScript]:
    """Find symlinks named lcc-* under bin_dir.

    Non-symlinks and unrelated names are ignored. A dangling symlink is
    reported with target=None.
    """
    results: list[DeployedScript] = []
    if not bin_dir.is_dir():
        return results

    for entry in sorted(bin_dir.iterdir()):
        if not entry.name.startswith("lcc-"):
            continue
        if not entry.is_symlink():
            continue
        try:
            target: Path | None = entry.resolve(strict=True)
        except (FileNotFoundError, OSError):
            target = None
        results.append(DeployedScript(name=entry.name, symlink=entry, target=target))

    return results


def detect_launch_agents(launch_agents_dir: Path) -> list[LaunchAgentInfo]:
    """Find plist files with labels starting com.lazy."""
    results: list[LaunchAgentInfo] = []
    if not launch_agents_dir.is_dir():
        return results

    for plist in sorted(launch_agents_dir.glob("com.lazy*.plist")):
        label = plist.stem
        results.append(LaunchAgentInfo(label=label, plist_path=plist))

    return results


def detect_qmd() -> bool:
    """Return True if the qmd CLI is available on PATH."""
    return shutil.which("qmd") is not None


def detect_state(
    *,
    home: Path,
    config_file_override: Path | None = None,
    bin_dir: Path | None = None,
    launch_agents_dir: Path | None = None,
) -> DetectedState:
    """Top-level orchestrator: scan system and return a DetectedState.

    All arguments are keyword-only. If bin_dir or launch_agents_dir are not
    provided, sensible defaults are derived from `home`. The config file
    defaults to the lazy-harness standard location via `default_config_file()`.
    """
    state = DetectedState()

    state.claude_code = detect_claude_code(home / ".claude")
    state.lazy_claudecode = detect_lazy_claudecode(home)

    cfg_path = config_file_override if config_file_override is not None else default_config_file()
    if cfg_path.is_file():
        state.lazy_harness_config = cfg_path

    bdir = bin_dir if bin_dir is not None else (home / ".local" / "bin")
    state.deployed_scripts = detect_deployed_scripts(bdir)

    la_dir = launch_agents_dir if launch_agents_dir is not None else (
        home / "Library" / "LaunchAgents"
    )
    state.launch_agents = detect_launch_agents(la_dir)

    state.qmd_available = detect_qmd()

    return state
