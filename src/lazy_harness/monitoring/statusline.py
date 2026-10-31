"""Statusline renderer for Claude Code.

Claude Code's statusline pipes a JSON payload to the configured command on
every redraw and shows whatever the command writes to stdout. This module
parses that payload and renders a single-line summary of who and where the
session is:

    profile model dir @branch

Context, cost and cache figures are left to mods drawn above the prompt.

The implementation is intentionally pure: `format_statusline` takes a dict
and returns a string, so it's trivial to test. The CLI wrapper in
cli/statusline_cmd.py reads stdin, parses JSON, and delegates here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _agent_runtime_dir() -> Path:
    """Runtime config dir of the configured agent (ADR-032 L3).

    Imports are kept local so importing this module stays cheap; the Claude
    Code adapter is the bootstrap default when no config is loadable, which
    resolves exactly like the historical CLAUDE_CONFIG_DIR read.
    """
    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.config import ConfigError, load_config
        from lazy_harness.core.paths import agent_runtime_dir, config_file
    except ImportError:
        # Broken install: fall back to the pre-ADR-032 env read so the
        # statusline keeps rendering instead of crashing.
        return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")

    cfg = None
    cf = config_file()
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None
    return agent_runtime_dir(get_agent(cfg.agent.type if cfg is not None else "claude-code"))


def _profile_label() -> str:
    """The profile this session is running under.

    Asked of `profile_name()` first, which matches each configured profile's
    own agent env var against that profile's `config_dir`. Deriving it here
    from `[agent].type`'s runtime dir could only ever name a profile running
    the global agent: a `agent = "codex"` profile has `CODEX_HOME` set and
    `CLAUDE_CONFIG_DIR` unset, so it fell through to the global link and got
    labelled `default` — the label for no profile at all.

    The directory surgery below stays as the fallback for a machine with no
    config, or whose agent dir no profile declares.

    Examples (Claude Code):
      ~/.claude-lazy → 'lazy'
      ~/.claude-flex → 'flex'
      ~/.claude      → 'default'
    """
    try:
        from lazy_harness.hooks.builtins._shared import profile_name
    except ImportError:
        # Broken install: the surgery below needs no lazy_harness internals.
        pass
    else:
        declared = profile_name()
        if declared:
            return declared

    config_dir = str(_agent_runtime_dir())
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


def format_statusline(payload: dict[str, Any]) -> str:
    """Build the statusline string from a Claude Code payload dict."""
    profile = _profile_label()
    model = _safe_get(payload, "model", "display_name") or ""
    branch = _safe_get(payload, "worktree", "branch") or ""
    cwd = _safe_get(payload, "workspace", "current_dir") or ""
    dir_name = os.path.basename(cwd.rstrip("/")) if cwd else ""

    parts: list[str] = [profile]
    if model and model != "?":
        parts.append(model)
    if dir_name:
        parts.append(dir_name)
    if branch:
        parts.append(f"@{branch}")

    return " ".join(parts)
