"""Tell the operator, once, when a session's context has grown past rotating.

`herdr-context-gauge` already measures this and paints the pane red at
`ROTATE_TOKENS`, but a colour on a pane is a display, not a prompt: measured
over 72h across both profiles, nine interactive sessions crossed 400k and none
of them were rotated — zero compactions in 52 sessions, with peaks reaching
569k and durations reaching 43 hours. The signal was right and unread.

This hook consumes that same number and says so in a `systemMessage`, which
ADR-030 G2 established as the non-blocking shape. It never touches the Stop
decision: a context warning that can interrupt a turn costs more than the
context it saves.

Kill criteria, declared before deployment as behavioural automation must be:

- Baseline (2026-09-12, 72h, both profiles), measured with `context_tokens` on
  the closing turn — the same reader this hook fires on, not the session's peak,
  because a criterion read against a different number than the trigger uses
  cannot judge the trigger: 9 of 387 sessions closed at or above 400k (5 lazy,
  4 flex), 0 compactions recorded across 52 interactive sessions. Highest close:
  824k.
- Horizon: 15 days, re-measured the same way.
- Remove it if sessions closing above 400k have not fallen below 6 per 72h, or
  if compactions are still zero. A notice nobody acts on is worse than silence,
  because it trains the operator to skip the next one.

The threshold is imported rather than restated, so the message and the pane
colour cannot drift apart.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from lazy_harness.hooks.builtins.herdr_context_gauge import (
    ROTATE_TOKENS,
    _format_tokens,
    context_tokens,
)

__all__ = ["ROTATE_TOKENS", "main", "notice", "stamp_dir"]


def stamp_dir() -> Path:
    """Where the once-per-session marker lives. Patched in tests."""
    return Path(tempfile.gettempdir())


def _stamp_for(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id) or "unknown"
    return stamp_dir() / f"lh-ctx-rotate-{safe}.stamp"


def notice(tokens: int) -> str:
    """The message itself: the number, then the two ways out of it."""
    return (
        f"🔴 {_format_tokens(tokens)} de contexto — arriba del umbral de rotación. "
        f"/compact <hint> si el task sigue, /clear si terminó."
    )


def _already_warned(stamp: Path) -> bool:
    """True when this session was already told.

    Fails open on an unreadable stamp: warning twice is noise, while failing
    closed would silence the notice for the rest of the session.
    """
    try:
        return stamp.exists()
    except OSError:
        return False


def _record(stamp: Path) -> None:
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text("1", encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    # Every path below exits 0. A gauge must never take down the turn it
    # measures, so a malformed payload, a vanished transcript and an
    # unwritable stamp all resolve to silence rather than to an error.
    try:
        raw = sys.stdin.read()
    except OSError:
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        sys.exit(0)

    if not isinstance(payload, dict):
        sys.exit(0)

    transcript = payload.get("transcript_path")
    if not isinstance(transcript, str) or not transcript:
        sys.exit(0)

    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        session_id = ""

    try:
        tokens = context_tokens(Path(transcript))
    except Exception:
        sys.exit(0)

    if tokens is None or tokens < ROTATE_TOKENS:
        sys.exit(0)

    stamp = _stamp_for(session_id)
    if _already_warned(stamp):
        sys.exit(0)

    # Top level, not inside `hookSpecificOutput`. Claude Code's hook schema
    # (verified against the 2.1.269 binary) lists `systemMessage` among the
    # common "Fields:" — "Display a message to the user (all hooks)" — while
    # `hookSpecificOutput` takes exactly four keys: additionalContext,
    # permissionDecision, permissionDecisionReason and updatedInput. Nesting it
    # parses fine and is then discarded, giving a hook that runs, stamps, logs,
    # and shows nothing.
    print(json.dumps({"systemMessage": notice(tokens)}))
    _record(stamp)
    sys.exit(0)


if __name__ == "__main__":
    main()
