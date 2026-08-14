"""Deploy orchestration — symlinks profiles, hooks, skills."""

from __future__ import annotations

import json
import sys

import click

from lazy_harness.core.config import Config
from lazy_harness.core.paths import config_dir, expand_path
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


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _entry_commands(entry: dict) -> list[str]:
    """Command strings carried by a single settings.json hook entry."""
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return []
    commands: list[str] = []
    for h in hooks:
        if isinstance(h, dict):
            cmd = h.get("command")
            if isinstance(cmd, str):
                commands.append(cmd)
    return commands


def _is_harness_owned(command: str) -> bool:
    """Whether the harness generated this command.

    Every generated command points at a builtin under
    `lazy_harness/hooks/builtins/`, so the marker survives a change of install
    prefix or interpreter — matching on the current `sys.executable` would not.
    """
    return "lazy_harness/hooks/builtins/" in command.replace("\\", "/")


def _normalize_entry(entry: dict) -> tuple[dict, list[str]]:
    """Coerce a foreign hook entry into the schema Claude Code accepts.

    Returns the repaired entry and a description of each repair. A non-string
    matcher is the one seen in the wild: an installer writing `null` for "no
    matcher" makes Claude Code reject the entire settings file, which silently
    disables every unrelated hook in the profile.
    """
    repairs: list[str] = []
    fixed = dict(entry)
    matcher = fixed.get("matcher")
    if matcher is None:
        fixed["matcher"] = ""
        repairs.append('matcher: null -> ""')
    elif not isinstance(matcher, str):
        fixed["matcher"] = ""
        repairs.append(f'matcher: {type(matcher).__name__} -> ""')
    return fixed, repairs


def _merge_hook_blocks(
    existing: object, generated: dict
) -> tuple[dict, list[tuple[str, str]], list[tuple[str, str, str]]]:
    """Merge harness-generated hooks over an existing settings.json hooks block.

    Harness-owned entries are replaced by the freshly generated ones; everything
    else belongs to another tool and is carried through, repaired if its schema
    would make Claude Code reject the file. Events the harness does not model are
    passed through untouched rather than dropped.

    Returns the merged block, the preserved entries as `(event, command)`, and
    the repairs as `(event, description, command)`.
    """
    merged: dict = {event: list(entries) for event, entries in generated.items()}
    preserved: list[tuple[str, str]] = []
    repaired: list[tuple[str, str, str]] = []
    if not isinstance(existing, dict):
        return merged, preserved, repaired

    generated_commands = {
        cmd
        for entries in generated.values()
        for entry in entries
        if isinstance(entry, dict)
        for cmd in _entry_commands(entry)
    }

    for event, entries in existing.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            commands = _entry_commands(entry)
            if not commands:
                continue
            if all(_is_harness_owned(cmd) for cmd in commands):
                continue
            # Already emitted this run — the tool's own installer wrote it and
            # config declares it too. Keeping both would run the hook twice.
            if all(cmd in generated_commands for cmd in commands):
                continue
            fixed, fixes = _normalize_entry(entry)
            for fix in fixes:
                repaired.append((event, fix, commands[0]))
            merged.setdefault(event, []).append(fixed)
            preserved.append((event, commands[0]))

    return merged, preserved, repaired


def deploy_hooks(cfg: Config) -> None:
    """Generate agent-native hook config for each profile."""
    from lazy_harness.agents.base import HookEntry
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.deploy.defaults import merge_with_defaults
    from lazy_harness.hooks.loader import resolve_script_names

    agent = get_agent(cfg.agent.type)

    effective = merge_with_defaults(cfg.hooks, agent)
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

    # Third-party commands declared in config are emitted to every profile, so a
    # tool's hooks stop depending on which profile its installer happened to run
    # against. Appended after the harness scripts, including on events whose
    # scripts list is empty.
    for event_name, event_cfg in cfg.hooks.items():
        for ext in event_cfg.external:
            hook_entries.setdefault(event_name, []).append(
                HookEntry(command=ext.command, matcher=ext.matcher)
            )

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

        if not isinstance(settings, dict):
            settings = {}
        existing_hooks = settings.get("hooks", {})
        merged, preserved, repaired = _merge_hook_blocks(existing_hooks, agent_hooks)

        if repaired:
            backup = settings_file.with_suffix(".json.bak")
            backup.write_text(existing_raw)
            click.echo(
                f"  ⚠  {name}/settings.json: repaired {len(repaired)} hook "
                f"{_plural(len(repaired), 'entry', 'entries')} Claude Code would reject "
                f"(the whole file is discarded on one bad field); "
                f"backup saved to {backup.name}."
            )
            for event, fix, cmd in repaired:
                click.echo(f"      {event:<20} {fix}   {cmd[:60]}")

        if preserved:
            click.echo(
                f"  ·  {name}/settings.json: preserved {len(preserved)} hook "
                f"{_plural(len(preserved), 'entry', 'entries')} not managed by the harness."
            )
            for event, cmd in preserved:
                click.echo(f"      {event:<20} {cmd[:60]}")

        settings["hooks"] = merged
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        click.echo(f"  ✓ {name}/settings.json (hooks updated)")


def _collect_mcp_servers(cfg: Config) -> dict[str, dict]:
    """Probe each known tool and return the MCP entries that should ship."""
    from lazy_harness.knowledge import graphify, qmd
    from lazy_harness.memory import engram

    servers: dict[str, dict] = {}
    if qmd.is_qmd_available():
        servers["qmd"] = qmd.mcp_server_config()
    if cfg.memory.engram.enabled and engram.is_engram_available():
        servers["engram"] = engram.mcp_server_config()
    # Graphify shipped a CLI-only entry point before 0.9; the MCP binary is
    # probed separately so older installs keep the skill-only surface.
    if cfg.knowledge.structure.enabled and graphify.is_graphify_mcp_available():
        servers["graphify"] = graphify.mcp_server_config()
    return servers


def deploy_mcp_servers(cfg: Config) -> None:
    """Write detected MCP server entries into each profile's agent MCP config file."""
    from lazy_harness.agents.registry import get_agent

    servers = _collect_mcp_servers(cfg)
    if not servers:
        click.echo("  No MCP servers detected — nothing to deploy.")
        return

    agent = get_agent(cfg.agent.type)
    mcp_file_name = agent.mcp_config_file()
    if not mcp_file_name:
        click.echo("  Agent does not use a separate MCP config file — skipping.")
        return

    mcp_block = agent.generate_mcp_config(servers)

    for name, entry in cfg.profiles.items.items():
        target_dir = expand_path(entry.config_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        mcp_config_file = target_dir / mcp_file_name

        existing: dict = {}
        if mcp_config_file.is_file():
            try:
                existing = json.loads(mcp_config_file.read_text())
            except json.JSONDecodeError:
                pass

        existing_mcp = existing.get("mcpServers", {})
        existing_mcp.update(mcp_block.get("mcpServers", {}))
        existing["mcpServers"] = existing_mcp

        mcp_config_file.write_text(json.dumps(existing, indent=2) + "\n")
        click.echo(f"  ✓ {name}/{mcp_file_name} (MCP servers: {', '.join(servers)})")


def deploy_claude_symlink(cfg: Config) -> None:
    """Create the agent's global config symlink to the default profile's config dir."""
    from lazy_harness.agents.registry import get_agent

    agent = get_agent(cfg.agent.type)
    link_path = agent.global_config_link()
    if link_path is None:
        return

    default_name = cfg.profiles.default
    entry = cfg.profiles.items.get(default_name)
    if not entry:
        return

    target = expand_path(entry.config_dir)
    status = ensure_symlink(target, link_path)
    if status == "exists":
        click.echo(f"  · {link_path} → {entry.config_dir} (already linked)")
    else:
        click.echo(f"  ✓ {link_path} → {entry.config_dir}")
