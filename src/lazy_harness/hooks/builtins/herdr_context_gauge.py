"""Publish this session's context usage onto its Herdr pane.

An orchestrator driving workers through `herdr agent prompt` has no way to see
that a reused worker's window has grown: `herdr agent get` reports lifecycle
state, never context. Without that signal it keeps prompting the same agent and
every turn re-reads a larger window. This hook supplies the missing datum as
pane metadata, so it surfaces in the `herdr agent list` output the orchestrator
already reads at harvest time.

Panes outlive the sessions inside them and pane metadata is persistent, so
publishing alone leaves a dead session's window on display indefinitely. The
hook therefore runs on three events: `Stop` publishes, `SessionEnd` retracts,
and `SessionStart` retracts unless the session resumed a real window.

Fail-soft: every error path exits 0, because a gauge must never take down the
turn it is measuring.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

from lazy_harness.hooks.builtins._shared import transcript_from_payload

WARN_TOKENS = 200_000
ROTATE_TOKENS = 400_000
PUBLISH_TIMEOUT_SECS = 5
METADATA_SOURCE = "lh:ctx"
THROTTLE_SECS = 60.0

_USAGE_INPUT_KEYS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _usage_of(entry: object) -> Mapping[str, object] | None:
    if not isinstance(entry, Mapping) or entry.get("type") != "assistant":
        return None
    message = entry.get("message")
    if not isinstance(message, Mapping):
        return None
    usage = message.get("usage")
    return usage if isinstance(usage, Mapping) else None


def context_tokens(transcript: Path) -> int | None:
    """Tokens the last turn actually sent, or None if the transcript says nothing.

    This is the live window, not the session's cumulative spend: every turn
    re-reads the whole window, so summing turns would report a number roughly
    three orders of magnitude too large.
    """
    latest: int | None = None
    try:
        with transcript.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                usage = _usage_of(entry)
                if usage is None:
                    continue
                latest = sum(
                    value for key in _USAGE_INPUT_KEYS if isinstance(value := usage.get(key), int)
                )
    except OSError:
        return None
    return latest


def _format_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens < 1_000:
        return "<1k"
    return f"{tokens // 1_000}k"


def gauge_label(tokens: int) -> str:
    """Traffic light for a pane's context, with the action inline when red."""
    size = _format_tokens(tokens)
    if tokens >= ROTATE_TOKENS:
        return f"🔴 {size} rotar"
    if tokens >= WARN_TOKENS:
        return f"🟡 {size}"
    return f"🟢 {size}"


def _metadata_command(pane_id: str, *tail: str) -> list[str]:
    return ["herdr", "pane", "report-metadata", pane_id, "--source", METADATA_SOURCE, *tail]


def publish_command(pane_id: str, label: str) -> list[str]:
    return _metadata_command(pane_id, "--display-agent", label)


def clear_command(pane_id: str) -> list[str]:
    """Retract the gauge, naming the source that published it."""
    return _metadata_command(pane_id, "--clear-display-agent")


def stamp_path(pane_id: str) -> Path:
    """Where this pane records when it last published."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", pane_id)
    return Path(tempfile.gettempdir()) / f"lh-ctx-gauge-{safe}.stamp"


def throttled(stamp: Path, now: float) -> bool:
    """True when a publish already happened inside the current window.

    Fails open on anything unreadable: publishing once too often costs a
    subprocess, while failing closed would freeze the pane for the session.
    """
    try:
        last = float(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return 0 <= now - last < THROTTLE_SECS


def _record_publish(stamp: Path, now: float) -> None:
    try:
        stamp.write_text(str(now), encoding="utf-8")
    except OSError:
        pass


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


def _tokens_of(payload: dict[str, object]) -> int | None:
    transcript = transcript_from_payload(payload)
    return None if transcript is None else context_tokens(transcript)


def main() -> None:
    if os.environ.get("HERDR_ENV") != "1":
        sys.exit(0)
    pane_id = os.environ.get("HERDR_PANE_ID")
    if not pane_id:
        sys.exit(0)

    payload = _read_stdin_json()
    event = payload.get("hook_event_name")
    now = time.time()
    stamp = stamp_path(pane_id)

    # Mid-turn samples are throttled; the lifecycle events are not. Bail before
    # reading the transcript — this path runs on every single tool call.
    if event == "PostToolUse" and throttled(stamp, now):
        sys.exit(0)

    tokens = None if event == "SessionEnd" else _tokens_of(payload)
    command = (
        clear_command(pane_id) if tokens is None else publish_command(pane_id, gauge_label(tokens))
    )
    _record_publish(stamp, now)

    try:
        subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=PUBLISH_TIMEOUT_SECS,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
