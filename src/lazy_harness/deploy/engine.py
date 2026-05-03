"""Deploy orchestration — symlinks profiles, hooks, skills."""

from __future__ import annotations

import json
import sys

import click

from lazy_harness.core.config import Config
from lazy_harness.core.paths import _home, config_dir, expand_path
from lazy_harness.deploy.symlinks import ensure_symlink


def deploy_profiles(cfg: Config) -> None:
    """Deploy profile content as symlinks to agent config dirs."""
    profiles_src = config_dir() / "profiles"
    if not profiles_src.is_dir():
        click.echo("No profiles directory found. Run: lh init")
        return

    for name, entry in cfg.profiles.items.items():
        src_dir = profiles_src / name
        if not src_dir.is_dir():
            click.echo(f"  · Profile '{name}' has no content dir at {src_dir}")
            continue

        target_dir = expand_path(entry.config_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        for item in src_dir.iterdir():
            target = target_dir / item.name
            status = ensure_symlink(item, target)
            if status == "exists":
                click.echo(f"  · {name}/{item.name} (already linked)")
            else:
                click.echo(f"  ✓ {name}/{item.name}")


def deploy_hooks(cfg: Config) -> None:
    """Generate agent-native hook config for each profile."""
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.hooks.loader import resolve_hooks_for_event

    agent = get_agent(cfg.agent.type)

    hook_commands: dict[str, list[str]] = {}
    for event_name in cfg.hooks:
        hooks = resolve_hooks_for_event(cfg, event_name)
        if hooks:
            commands: list[str] = []
            for hook in hooks:
                commands.append(f"{sys.executable} {hook.path}")
            hook_commands[event_name] = commands

    if not hook_commands:
        click.echo("  No hooks to deploy.")
        return

    agent_hooks = agent.generate_hook_config(hook_commands)

    for name, entry in cfg.profiles.items.items():
        target_dir = expand_path(entry.config_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        settings_file = target_dir / "settings.json"

        settings: dict = {}
        if settings_file.is_file():
            try:
                settings = json.loads(settings_file.read_text())
            except json.JSONDecodeError:
                pass

        settings["hooks"] = agent_hooks
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        click.echo(f"  ✓ {name}/settings.json (hooks updated)")


def _collect_mcp_servers(cfg: Config) -> dict[str, dict]:
    """Probe each known tool and return the MCP entries that should ship."""
    from lazy_harness.knowledge import qmd

    servers: dict[str, dict] = {}
    if qmd.is_qmd_available():
        servers["qmd"] = qmd.mcp_server_config()
    return servers


def deploy_mcp_servers(cfg: Config) -> None:
    """Write detected MCP server entries into each profile's settings.json."""
    from lazy_harness.agents.registry import get_agent

    servers = _collect_mcp_servers(cfg)
    if not servers:
        click.echo("  No MCP servers detected — nothing to deploy.")
        return

    agent = get_agent(cfg.agent.type)
    mcp_block = agent.generate_mcp_config(servers)

    for name, entry in cfg.profiles.items.items():
        target_dir = expand_path(entry.config_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        settings_file = target_dir / "settings.json"

        settings: dict = {}
        if settings_file.is_file():
            try:
                settings = json.loads(settings_file.read_text())
            except json.JSONDecodeError:
                pass

        settings.update(mcp_block)
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        click.echo(f"  ✓ {name}/settings.json (MCP servers: {', '.join(servers)})")


def deploy_claude_symlink(cfg: Config) -> None:
    """Create ~/.claude symlink to default profile's config dir."""
    default_name = cfg.profiles.default
    entry = cfg.profiles.items.get(default_name)
    if not entry:
        return

    claude_link = _home() / ".claude"
    target = expand_path(entry.config_dir)

    status = ensure_symlink(target, claude_link)
    if status == "exists":
        click.echo(f"  · ~/.claude → {entry.config_dir} (already linked)")
    else:
        click.echo(f"  ✓ ~/.claude → {entry.config_dir}")
