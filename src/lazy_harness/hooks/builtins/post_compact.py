#!/usr/bin/env python3
"""PostCompact hook: re-inject pre-compact summary into post-compact context.

Reads `pre-compact-summary.md` (written by the pre-compact hook) and re-emits
it as `hookSpecificOutput.additionalContext` so Claude Code includes it in the
context window after compaction. Skips silently if the file is missing or its
mtime is older than `_FRESHNESS_WINDOW_SECONDS` (stale from a previous compact).

Always exits 0. Never blocks compaction recovery.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_FRESHNESS_WINDOW_SECONDS = 300


def _log(log_file: Path, msg: str) -> None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with open(log_file, "a") as f:
            f.write(f"{ts} post-compact: {msg}\n")
    except OSError:
        pass


def _strip_html_comments(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("<!--")).strip()


def main() -> None:
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        pass

    cwd = Path.cwd()
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    log_file = claude_dir / "logs" / "hooks.log"

    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    summary_file = claude_dir / "projects" / encoded / "memory" / "pre-compact-summary.md"

    try:
        st = summary_file.stat()
    except FileNotFoundError:
        _log(log_file, f"fired cwd={cwd} action=skipped reason=missing")
        return
    except OSError as e:
        _log(log_file, f"fired cwd={cwd} action=skipped reason=stat_error err={e}")
        return

    age = time.time() - st.st_mtime
    if age > _FRESHNESS_WINDOW_SECONDS:
        _log(log_file, f"fired cwd={cwd} action=skipped reason=stale age={age:.0f}s")
        return

    try:
        raw = summary_file.read_text()
    except OSError as e:
        _log(log_file, f"fired cwd={cwd} action=skipped reason=read_error err={e}")
        return

    body = _strip_html_comments(raw)
    if not body:
        _log(log_file, f"fired cwd={cwd} action=skipped reason=empty_body")
        return

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostCompact",
            "additionalContext": body,
        }
    }
    print(json.dumps(output))
    _log(log_file, f"fired cwd={cwd} action=injected summary_chars={len(body)}")


if __name__ == "__main__":
    main()
