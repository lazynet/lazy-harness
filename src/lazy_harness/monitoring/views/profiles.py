"""`lh status profiles` view — per-profile config, hooks count, MCP count, auth."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from rich.console import Console
from rich.table import Table

from lazy_harness.core.paths import contract_path
from lazy_harness.monitoring.views._helpers import StatusContext


def _auth_email(config_dir: Path) -> str:
    """Best-effort: ask `claude auth status` for the email under this config dir.

    Returns "" on any error. Bounded by a 5s timeout because the command can
    block on network / login flows in the worst case.
    """
    if not config_dir.is_dir():
        return ""
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    try:
        result = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        if result.stdout:
            data = json.loads(result.stdout)
            return data.get("email") or data.get("user", {}).get("email", "") or ""
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return ""


def _settings_counts(config_dir: Path) -> tuple[int, int]:
    """Return (hook_count, mcp_count) read from settings.json."""
    settings_file = config_dir / "settings.json"
    if not settings_file.is_file():
        return 0, 0
    try:
        settings = json.loads(settings_file.read_text())
    except (json.JSONDecodeError, OSError):
        return 0, 0
    hook_count = 0
    for hook_list in settings.get("hooks", {}).values():
        if isinstance(hook_list, list):
            hook_count += sum(
                len(h.get("hooks", [])) if isinstance(h, dict) else 0 for h in hook_list
            )
    mcp_count = len(settings.get("mcpServers", {}))
    return hook_count, mcp_count


def render(ctx: StatusContext, console: Console) -> None:
    table = Table(show_header=True, pad_edge=False)
    table.add_column("Profile", style="bold")
    table.add_column("Config Dir")
    table.add_column("Status")
    table.add_column("Auth")
    table.add_column("Hooks", justify="right")
    table.add_column("MCPs", justify="right")

    for p in ctx.profiles:
        label = f"{p.name} (default)" if p.is_default else p.name
        if not p.exists:
            status = "[red]missing[/red]"
        elif (p.config_dir / "settings.json").is_file():
            status = "[green]configured[/green]"
        else:
            status = "[yellow]exists[/yellow]"

        hooks, mcps = _settings_counts(p.config_dir)
        email = _auth_email(p.config_dir) or "—"
        table.add_row(
            label,
            contract_path(p.config_dir),
            status,
            email,
            str(hooks),
            str(mcps),
        )

    console.print(table)
