"""Stop hook — publish this session's context usage onto its Herdr pane.

An orchestrator driving workers through `herdr agent prompt` has no way to see
that a reused worker's window has grown: `herdr agent get` reports lifecycle
state, never context. Without that signal it keeps prompting the same agent and
every turn re-reads a larger window. This hook supplies the missing datum as
pane metadata, so it surfaces in the `herdr agent list` output the orchestrator
already reads at harvest time.

Fail-soft: every error path exits 0, because a gauge must never take down the
turn it is measuring.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from lazy_harness.hooks.builtins._shared import transcript_from_payload

WARN_TOKENS = 200_000
ROTATE_TOKENS = 400_000
PUBLISH_TIMEOUT_SECS = 5
METADATA_SOURCE = "lh:ctx"

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


def publish_command(pane_id: str, label: str) -> list[str]:
    return [
        "herdr",
        "pane",
        "report-metadata",
        pane_id,
        "--source",
        METADATA_SOURCE,
        "--display-agent",
        label,
    ]


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


def main() -> None:
    if os.environ.get("HERDR_ENV") != "1":
        sys.exit(0)
    pane_id = os.environ.get("HERDR_PANE_ID")
    if not pane_id:
        sys.exit(0)

    transcript = transcript_from_payload(_read_stdin_json())
    if transcript is None:
        sys.exit(0)
    tokens = context_tokens(transcript)
    if tokens is None:
        sys.exit(0)

    try:
        subprocess.run(
            publish_command(pane_id, gauge_label(tokens)),
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
