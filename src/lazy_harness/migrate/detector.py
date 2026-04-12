from __future__ import annotations

from pathlib import Path

from lazy_harness.migrate.state import ClaudeCodeSetup


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
