"""PATH resolution shared by every scheduler backend.

A scheduled job inherits nothing from a login shell — launchd builds the
environment from the plist, systemd from the unit, and cron from a minimal
built-in default. PATH is the single most common reason such a job fails, so
all three backends derive it the same way rather than each carrying its own
hardcoded string.
"""

from __future__ import annotations

import os
from pathlib import Path

_FALLBACK = "/usr/local/bin:/usr/bin:/bin"


def _is_ephemeral(entry: str) -> bool:
    """Whether this PATH entry will not outlive the process generating it.

    A scheduled unit is written once and read for months, so it must not
    reference the interpreter that produced it. Running `lh scheduler install`
    under `uv run` from a worktree put that worktree's `.venv/bin` into the
    generated PATH — a directory `/cleanup-worktree` deletes, after which the
    job fails with nothing reporting why.

    Scoped to virtualenvs rather than every ephemeral root: a temp directory
    on PATH is pathological but not this tool's business, and the one case
    seen in practice came from a test redirecting `$HOME`, which the suite now
    blocks at the `crontab` boundary instead.
    """
    resolved = Path(entry).resolve()
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        try:
            resolved.relative_to(Path(venv).resolve())
            return True
        except ValueError:
            pass
    parts = resolved.parts
    return ".venv" in parts or "site-packages" in parts


def resolved_path() -> str:
    """The PATH to write into a scheduled unit.

    Built from the invoking environment, filtered to directories that exist,
    with `~/.local/bin` prepended — that is where `uv tool install` puts `lh`,
    and a unit that cannot find `lh` fails in a way nothing reports.
    """
    raw = os.environ.get("PATH") or _FALLBACK
    entries: list[str] = []
    for entry in raw.split(os.pathsep):
        if not entry or entry in entries or not Path(entry).is_dir():
            continue
        if _is_ephemeral(entry):
            continue
        entries.append(entry)

    if not entries:
        # The fallback used to apply to the input, so a PATH made entirely of
        # venv bins left the unit with ~/.local/bin alone — no /usr/bin, so
        # the job cannot even find `sh`.
        entries = [e for e in _FALLBACK.split(os.pathsep) if Path(e).is_dir()] or list(
            _FALLBACK.split(os.pathsep)
        )

    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin in entries:
        entries.remove(local_bin)
    entries.insert(0, local_bin)
    return os.pathsep.join(entries)
