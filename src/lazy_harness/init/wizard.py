from __future__ import annotations

from pathlib import Path

from lazy_harness.migrate.detector import detect_claude_code, detect_lazy_claudecode


class ExistingSetupError(Exception):
    """Raised when lh init is run on a system with an existing setup."""


def check_existing_setup(*, home: Path, lh_config: Path) -> None:
    """Raise ExistingSetupError if any pre-existing setup is detected.

    Checks, in order:
    1. An existing lazy-harness config.toml
    2. A vanilla Claude Code install at ~/.claude/
    3. lazy-claudecode multi-profile dirs (~/.claude-*)
    """
    if lh_config.is_file():
        raise ExistingSetupError(
            "lazy-harness is already configured. Use `lh init --force` "
            "to reinitialize (existing config will be backed up)."
        )
    cc = detect_claude_code(home / ".claude")
    if cc is not None:
        raise ExistingSetupError(
            "Detected existing Claude Code setup at ~/.claude/. "
            "To preserve your history, use `lh migrate` instead of `lh init`."
        )
    lc = detect_lazy_claudecode(home)
    if lc is not None:
        raise ExistingSetupError(
            f"Detected existing lazy-claudecode profiles: {', '.join(lc.profiles)}. "
            "Use `lh migrate` instead of `lh init`."
        )
