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


def _hook_commands(hook_block: dict) -> set[str]:
    """Collect every command string from a Claude Code hooks block."""
    commands: set[str] = set()
    if not isinstance(hook_block, dict):
        return commands
    for entries in hook_block.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for h in entry.get("hooks", []):
                if isinstance(h, dict):
                    cmd = h.get("command")
                    if isinstance(cmd, str):
                        commands.add(cmd)
    return commands


def _unknown_hook_commands(existing: dict, new: dict) -> list[str]:
    """Commands present in `existing` but absent from `new`, sorted for stable output."""
    return sorted(_hook_commands(existing) - _hook_commands(new))


def deploy_hooks(cfg: Config) -> None:
    """Generate agent-native hook config for each profile."""
    from lazy_harness.agents.base import HookEntry
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.deploy.defaults import merge_with_defaults
    from lazy_harness.hooks.loader import resolve_script_names

    agent = get_agent(cfg.agent.type)

    effective = merge_with_defaults(cfg.hooks)
    hook_entries: dict[str, list[str | HookEntry]] = {}
    for event_name, script_names in effective.items():
        if not script_names:
            continue
        hooks = resolve_script_names(script_names)
        if hooks:
            entries: list[str | HookEntry] = []
            for hook in hooks:
                command = f"{sys.executable} {hook.path}"
                if hook.matcher is not None:
                    entries.append(HookEntry(command=command, matcher=hook.matcher))
                else:
                    entries.append(command)
            hook_entries[event_name] = entries

    if not hook_entries:
        click.echo("  No hooks to deploy.")
        return

    agent_hooks = agent.generate_hook_config(hook_entries)

    for name, entry in cfg.profiles.items.items():
        target_dir = expand_path(entry.config_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        settings_file = target_dir / "settings.json"

        settings: dict = {}
        existing_raw = ""
        if settings_file.is_file():
            existing_raw = settings_file.read_text()
            try:
                settings = json.loads(existing_raw)
            except json.JSONDecodeError:
                settings = {}

        existing_hooks = settings.get("hooks", {}) if isinstance(settings, dict) else {}
        unknowns = _unknown_hook_commands(existing_hooks, agent_hooks)
        if unknowns:
            backup = settings_file.with_suffix(".json.bak")
            backup.write_text(existing_raw)
            click.echo(
                f"  ⚠  {name}/settings.json had {len(unknowns)} unknown hook "
                f"entries; backup saved to {backup.name}."
            )
            for cmd in unknowns:
                click.echo(f"      removed: {cmd[:80]}")

        settings["hooks"] = agent_hooks
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        click.echo(f"  ✓ {name}/settings.json (hooks updated)")


def _collect_mcp_servers(cfg: Config) -> dict[str, dict]:
    """Probe each known tool and return the MCP entries that should ship.

    Graphify is intentionally excluded: per upstream (safishamsi/graphify) it's
    a CLI/skill installed via `graphify install`, not an MCP server. The
    `graphify mcp` subcommand does not exist.
    """
    from lazy_harness.knowledge import qmd
    from lazy_harness.memory import engram

    servers: dict[str, dict] = {}
    if qmd.is_qmd_available():
        servers["qmd"] = qmd.mcp_server_config()
    if cfg.memory.engram.enabled and engram.is_engram_available():
        servers["engram"] = engram.mcp_server_config()
    return servers


def deploy_mcp_servers(cfg: Config) -> None:
    """Write detected MCP server entries into each profile's .claude.json.

    Claude Code reads MCP servers from .claude.json (not settings.json), so
    that's where the deploy must merge them. The rest of .claude.json
    (history, projects, userID, ...) is preserved untouched.
    """
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
        claude_json_file = target_dir / ".claude.json"

        existing: dict = {}
        if claude_json_file.is_file():
            try:
                existing = json.loads(claude_json_file.read_text())
            except json.JSONDecodeError:
                pass

        existing_mcp = existing.get("mcpServers", {})
        existing_mcp.update(mcp_block.get("mcpServers", {}))
        existing["mcpServers"] = existing_mcp

        claude_json_file.write_text(json.dumps(existing, indent=2) + "\n")
        click.echo(f"  ✓ {name}/.claude.json (MCP servers: {', '.join(servers)})")


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
