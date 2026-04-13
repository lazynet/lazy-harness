"""Statusline renderer for Claude Code.

Claude Code's statusline pipes a JSON payload to the configured command on
every redraw and shows whatever the command writes to stdout. This module
parses that payload and renders a single-line summary:

    profile model dir @branch | <in>K/<out>K tok $X.XX | NN% free

The implementation is intentionally pure: `format_statusline` takes a dict
and returns a string, so it's trivial to test. The CLI wrapper in
cli/statusline_cmd.py reads stdin, parses JSON, and delegates here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _profile_label() -> str:
    """Derive the profile name from CLAUDE_CONFIG_DIR.

    Examples:
      ~/.claude-lazy → 'lazy'
      ~/.claude-flex → 'flex'
      ~/.claude      → 'default'
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    base = os.path.basename(config_dir.rstrip("/"))
    if base.startswith(".claude-"):
        return base[len(".claude-") :] or "default"
    if base == ".claude":
        return "default"
    return base or "default"


def _safe_get(payload: dict[str, Any], *keys: str) -> Any:
    cur: Any = payload
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _to_k(value: Any) -> str:
    """Convert a raw token count to 'NK' (round-half-up).

    Python's round() uses banker's rounding, so round(0.5) == 0. We want the
    classic schoolroom rounding that the bash implementation (`awk %.0f`) used,
    so half always rounds up. Returns '0' for missing/non-numeric input.
    """
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    return f"{int(n / 1000 + 0.5)}"


def format_statusline(payload: dict[str, Any]) -> str:
    """Build the statusline string from a Claude Code payload dict."""
    profile = _profile_label()
    model = _safe_get(payload, "model", "display_name") or ""
    branch = _safe_get(payload, "worktree", "branch") or ""
    cwd = _safe_get(payload, "workspace", "current_dir") or ""
    dir_name = os.path.basename(cwd.rstrip("/")) if cwd else ""
    in_tok = _safe_get(payload, "context_window", "total_input_tokens") or 0
    out_tok = _safe_get(payload, "context_window", "total_output_tokens") or 0
    cost = _safe_get(payload, "cost", "total_cost_usd") or 0
    free_pct = _safe_get(payload, "context_window", "remaining_percentage")

    parts: list[str] = [profile]
    if model and model != "?":
        parts.append(model)
    if dir_name:
        parts.append(dir_name)
    if branch:
        parts.append(f"@{branch}")

    try:
        cost_fmt = f"${float(cost):.2f}"
    except (TypeError, ValueError):
        cost_fmt = "$0.00"

    free_str = f"{free_pct}%" if free_pct not in (None, "") else "?%"

    return (
        f"{' '.join(parts)} | "
        f"{_to_k(in_tok)}K/{_to_k(out_tok)}K tok {cost_fmt} | "
        f"{free_str} free"
    )
