"""lh statusline — render a Claude Code statusline from JSON on stdin."""

from __future__ import annotations

import json
import sys

import click

from lazy_harness.monitoring.statusline import format_statusline


@click.command("statusline")
def statusline() -> None:
    """Read a Claude Code status payload on stdin and print the formatted line.

    Configured in profiles/<name>/settings.json as:
        "statusLine": { "type": "command", "command": "lh statusline" }
    """
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    click.echo(format_statusline(payload))
