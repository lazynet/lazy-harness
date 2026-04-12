from __future__ import annotations

from pathlib import Path

from lazy_harness.migrate.state import ClaudeCodeSetup, LazyClaudecodeSetup


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
