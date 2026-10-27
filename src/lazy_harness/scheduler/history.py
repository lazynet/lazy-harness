"""Log evidence for schedulers that do not expose execution timestamps."""

import re
from datetime import datetime
from pathlib import Path


def last_log_timestamp(log_file: Path) -> str:
    """Pull the most recent `[YYYY-MM-DD HH:MM:SS]` bracket-stamp from a log."""
    try:
        lines = log_file.read_text().splitlines()
    except OSError:
        return ""
    for line in reversed(lines[-50:]):
        match = re.search(r"\[([\d\- :.]+)\]", line)
        if match:
            return match.group(1).replace(" ", "T", 1)
    return ""


def last_run_from_logs(name: str) -> datetime | None:
    log_dir = Path.home() / ".local" / "share" / "lazy-harness" / "logs"
    for filename in (f"{name}-stdout.log", f"{name}.log", f"qmd-{name}.log"):
        log_path = log_dir / filename
        if not log_path.is_file():
            continue
        stamp = last_log_timestamp(log_path)
        if stamp:
            try:
                return datetime.fromisoformat(stamp)
            except ValueError:
                pass
        try:
            return datetime.fromtimestamp(log_path.stat().st_mtime)
        except OSError:
            continue
    return None
