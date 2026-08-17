"""PATH resolution shared by every scheduler backend.

A scheduled job inherits nothing from a login shell — launchd builds the
environment from the plist, systemd from the unit, and cron from a minimal
built-in default. PATH is the single most common reason such a job fails, so
all three backends derive it the same way rather than each carrying its own
hardcoded string.

The result is a property of the machine, never of the shell that ran
`lh scheduler install`. Deriving it from `os.environ["PATH"]` made a file that
is read for months depend on which terminal happened to generate it: on a
developer's Mac that meant pyenv shims ahead of Homebrew and app bundles in
the tail, while the same command over ssh produced five clean entries. A job
needing anything outside this set declares the full path in its command.
"""

from __future__ import annotations

import os
from pathlib import Path

# Ordered, and presence-gated rather than branched on `sys.platform`: an Intel
# Mac, an Apple Silicon Mac and a Linux box each keep the entries they have.
_STANDARD: tuple[str, ...] = (
    "/opt/homebrew/bin",  # Homebrew on Apple Silicon
    "/usr/local/bin",  # Homebrew on Intel, and the usual local prefix elsewhere
    "/usr/bin",
    "/bin",
)


def resolved_path() -> str:
    """The PATH to write into a scheduled unit."""
    # Unconditional, unlike the rest: this is where `uv tool install` puts
    # `lh`, so its absence when the unit is written is no evidence it will be
    # absent when the unit runs.
    entries = [str(Path.home() / ".local" / "bin")]
    entries.extend(d for d in _STANDARD if Path(d).is_dir())
    return os.pathsep.join(entries)
