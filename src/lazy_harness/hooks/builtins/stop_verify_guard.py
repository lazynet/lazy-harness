"""Stop hook: soft-enforce verification before a session with a declared goal closes.

See specs/designs/2026-08-16-loop-engineering-design.md, "Soft enforcement on
`Stop`". Once per session: if the session declared a goal (native `/goal
<condition>`) and no `verify_ran` event exists for it, the first Stop attempt
blocks with a reminder; the second closes regardless. The event is recorded
either way. Gated behind `[loops] inject_goal_prompt`, the same flag its
sibling `user_prompt_goal.py` uses — when it is off this hook does nothing.

Fail-soft: every path exits 0. A hook that raises takes down the chain.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BLOCK_REASON = (
    "Esta sesión declaró un goal (/goal) y todavía no hay evidencia de que "
    "corriste la verificación (skill verify-before-done) antes de cerrar. "
    "Verificá antes de terminar — este aviso no se repite en esta sesión."
)


def _goal_declared(transcript_path: Path) -> bool:
    """True if the transcript carries a native `/goal` declaration.

    `/goal <condition>` appends a `type: "attachment"` message whose
    `attachment.type` is `"goal_status"` to the transcript the moment the
    command runs — verified against Claude Code 2.1.266's own source and
    against real transcripts in this repo. That marker is written
    synchronously, well before any later `Stop` event, so it is safe to read
    here. This is a different, narrower signal than the compound-loop
    worker's `goal_declared`/`goal_absent` verdict: that one judges prose
    success criteria via an LLM classification made *after* the session ends
    and is structurally unavailable at `Stop` time.
    """
    try:
        with transcript_path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "attachment":
                    continue
                attachment = entry.get("attachment")
                if isinstance(attachment, dict) and attachment.get("type") == "goal_status":
                    return True
    except OSError:
        return False
    return False


def _read_stdin_json() -> dict[str, object]:
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _db_path() -> Path:
    from lazy_harness.monitoring.db import resolve_db_path

    return resolve_db_path()


def _injection_enabled() -> bool:
    try:
        from lazy_harness.core.config import load_config
        from lazy_harness.core.paths import config_file

        return bool(load_config(config_file()).loops.inject_goal_prompt)
    except Exception:
        return False


def _emit_block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}))


def main() -> None:
    try:
        if not _injection_enabled():
            sys.exit(0)

        payload = _read_stdin_json()
        session = payload.get("session_id")
        session_id = session if isinstance(session, str) and session else ""
        if not session_id:
            sys.exit(0)

        from lazy_harness.hooks.builtins._shared import (
            profile_name,
            project_key,
            transcript_from_payload,
        )

        transcript_path = transcript_from_payload(payload)
        if transcript_path is None or not _goal_declared(transcript_path):
            sys.exit(0)

        cwd = payload.get("cwd")
        project = project_key(Path(cwd)) if isinstance(cwd, str) and cwd else ""
        profile = profile_name()

        from lazy_harness.monitoring.db import MetricsDB

        db = MetricsDB(_db_path())

        if db.has_loop_event(session_id, "verify_ran"):
            sys.exit(0)

        if db.has_loop_event(session_id, "verify_block"):
            db.record_loop_event(
                session=session_id, kind="verify_skipped", project=project, profile=profile
            )
            sys.exit(0)

        db.record_loop_event(
            session=session_id, kind="verify_block", project=project, profile=profile
        )
        _emit_block(_BLOCK_REASON)
    except Exception:
        # A hook must degrade, never crash the chain: any failure here (bad
        # payload shape, an unreadable transcript, an unwritable metrics
        # store) is swallowed so the session continues uninterrupted.
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
