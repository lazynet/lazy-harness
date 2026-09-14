"""Deploy orchestration — symlinks profiles, hooks, skills."""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Collection
from pathlib import PurePosixPath

import click

from lazy_harness import __version__
from lazy_harness.agents.registry import DEFAULT_HARNESS_BINARY, binary_for_profile
from lazy_harness.core.artifact_version import (
    SETTINGS_BINARY_KEY,
    extract_binary_from_settings,
)
from lazy_harness.core.config import Config
from lazy_harness.core.paths import config_dir, expand_path
from lazy_harness.deploy.symlinks import ensure_symlink
from lazy_harness.hooks.loader import HookInfo

# The launcher invocation every generated builtin command takes. `hook_command`
# builds it and `_is_harness_owned` recognises it; both derive from these names
# so the generator and the classifier cannot drift apart again. The launcher
# itself is per profile since decision 11 — `DEFAULT_HARNESS_BINARY` is only
# what a profile that declares nothing gets.
_HOOK_SUBCOMMAND = "hook"

# Written by harness versions before the launcher existed, when a generated
# command was `{sys.executable} {path-under-builtins}`. Still recognised so a
# redeploy prunes those entries instead of preserving them as foreign.
_LEGACY_BUILTIN_MARKER = "lazy_harness/hooks/builtins/"


def hook_command(
    hook: HookInfo, *, profile: str, binary: str = DEFAULT_HARNESS_BINARY
) -> str:
    """The command string written into the agent's settings for this hook.

    Builtins go through `<binary> hook <name> --profile <profile>`. The binary is
    the one `binary_for_profile` resolves for this profile: a beta profile points
    its hooks at a separately installed launcher without any other profile
    noticing, which is what makes a profile the blast-radius boundary rather than
    an installation (decision 11, 2026-09-13 multi-agent design).

    It stays a bare name for the same reason the rest of the command does — see
    below — so declaring one is a promise that it is on `PATH`, not a path.

    The profile is the
    one fact a running hook needs and the one it cannot derive: it names the
    agent whose wire format the runner speaks, the config dir, the memory scope
    and the metrics label. An environment variable or a global config key would
    give two profiles on one machine the same answer, so it is written into the
    command — which is why the command is generated per profile rather than once
    for all of them.

    The command carries no path at all. The
    previous form, `f"{sys.executable} {hook.path}"`, baked in two
    machine-specific halves — the home directory appears in both, and the
    Python minor version appears in the site-packages path — so a
    chezmoi-managed settings file could never converge across two machines.

    A bare command name is resolved against PATH by `execvp` whether or not a
    shell is involved, which `$HOME/...` is not: that would have traded a
    portability problem for an assumption about how the agent spawns hooks.

    A user hook keeps an explicit interpreter and path. The framework did not
    ship it and has no stable launcher for it.

    The profile is quoted so that it stays one argument. Nothing validates a
    profile name — `core.config` reads the table keys as written — and
    interpolated bare, `--profile work laptop` reaches click as two arguments
    and exits 2 with a usage error. On PreToolUse exit 2 is how Claude Code is
    told to block the tool call, so the generated command would block the
    agent's tools rather than fail visibly.
    """
    if hook.is_builtin:
        return f"{binary} {_HOOK_SUBCOMMAND} {hook.name} --profile {shlex.quote(profile)}"
    return f"{sys.executable} {hook.path}"


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


def _is_harness_owned(
    command: str, *, binaries: Collection[str] = (DEFAULT_HARNESS_BINARY,)
) -> bool:
    """Whether the harness generated this command.

    Identity is the canonical hook name inside a launcher invocation — `<binary>
    hook <name>` — not the text of the command as a whole. Flags the harness
    adds later (`--profile <name>`) change that text on every entry, and a
    classifier keyed on text would then read its own previous output as another
    tool's hook and preserve it alongside the new one.

    `binaries` is what `_owned_binaries` reads off the artifact being merged —
    the launcher the file itself records as having written it, plus the one this
    deploy is about to write, plus the default. Deriving it from the live config
    instead is the defect this replaced: a profile rolled back off `lh-beta`
    dropped `lh-beta` from the set, so the entries the harness's own previous
    deploy had written became foreign and were preserved beside the new ones.
    A config cannot answer "did I write this" — only the artifact can.

    A `hook` subcommand alone is deliberately not enough to claim a command:
    another tool modelling hooks the same way would be adopted and then pruned.

    The predecessor matched on a builtins path, which `hook_command` stopped
    emitting when it moved to the launcher: it had been classifying every
    harness hook as foreign, masked only by the separate byte-identical check
    in `_merge_hook_blocks`.
    """
    normalised = command.replace("\\", "/")
    if _LEGACY_BUILTIN_MARKER in normalised:
        return True
    try:
        argv = shlex.split(normalised)
    except ValueError:
        return False
    if len(argv) < 3:
        return False
    if PurePosixPath(argv[0]).name not in binaries:
        return False
    if argv[1] != _HOOK_SUBCOMMAND:
        return False
    return not argv[2].startswith("-")


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


def _owned_binaries(settings: dict, binary: str) -> set[str]:
    """The launchers whose commands this settings file may legitimately carry.

    Three sources, none of them the live config:

    - the launcher the file records as having written it, so entries survive
      their binary being retired from every profile;
    - the launcher this deploy is writing, so a first deploy onto a file that
      records nothing still recognises what it is about to generate;
    - the default, which is what every settings.json written before the stamp
      existed necessarily used — no released version could emit another.

    The set stays closed: a launcher nobody ever deployed is never claimed.
    """
    owned = {DEFAULT_HARNESS_BINARY, binary}
    recorded = extract_binary_from_settings(settings)
    if recorded:
        owned.add(recorded)
    return owned


def _merge_hook_blocks(
    existing: object,
    generated: dict,
    *,
    binaries: Collection[str] = (DEFAULT_HARNESS_BINARY,),
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
            if all(_is_harness_owned(cmd, binaries=binaries) for cmd in commands):
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

    def entries_for(profile: str, binary: str) -> dict[str, list[str | HookEntry]]:
        """The hook entries one profile's settings file gets.

        Built per profile because `hook_command` names the profile and takes its
        binary: a single shared list would deploy every profile's hooks under
        whichever one happened to be generated first.
        """
        hook_entries: dict[str, list[str | HookEntry]] = {}
        for event_name, script_names in effective.items():
            if not script_names:
                continue
            hooks = resolve_script_names(script_names, event=event_name)
            if hooks:
                entries: list[str | HookEntry] = []
                for hook in hooks:
                    command = hook_command(hook, profile=profile, binary=binary)
                    if hook.matcher is not None:
                        entries.append(HookEntry(command=command, matcher=hook.matcher))
                    else:
                        entries.append(command)
                hook_entries[event_name] = entries

        # Third-party commands declared in config are emitted to every profile,
        # so a tool's hooks stop depending on which profile its installer
        # happened to run against. Appended after the harness scripts, including
        # on events whose scripts list is empty.
        for event_name, event_cfg in cfg.hooks.items():
            for ext in event_cfg.external:
                hook_entries.setdefault(event_name, []).append(
                    HookEntry(command=ext.command, matcher=ext.matcher)
                )
        return hook_entries

    # Whether there is anything to deploy does not depend on the profile: the
    # profile decides what each command says, not which hooks resolve.
    if not entries_for("", DEFAULT_HARNESS_BINARY):
        click.echo("  No hooks to deploy.")
        return

    for name, entry in cfg.profiles.items.items():
        binary = binary_for_profile(cfg, name)
        agent_hooks = agent.generate_hook_config(entries_for(name, binary))
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
        merged, preserved, repaired = _merge_hook_blocks(
            existing_hooks, agent_hooks, binaries=_owned_binaries(settings, binary)
        )

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

        # Decision 9 (2026-09-13 multi-agent blast radius design): the
        # managed section declares the version that wrote it, so a reader can
        # tell a settings.json newer than the running binary apart from a
        # stale one — see `lazy_harness.core.artifact_version`.
        #
        # Written at the document's top level, not inside the hooks block.
        # Measured directly (a `PreToolUse` hook that denies with a unique
        # reason string, fired via `claude -p` against a real settings file):
        # Claude Code parses and honours a settings file carrying an unknown
        # top-level key exactly as it does one carrying the same key inside
        # `hooks` — both are tolerated, so that axis does not decide it.
        # `settings["hooks"]` does: it is a `{event: [entry, ...]}` contract,
        # and every generic reader of that shape (this repo's own
        # `_harness_entry_count` test helper included) iterates every value
        # as a list of entries — a scalar there breaks the harness's own
        # readers first, which is exactly what smuggling this in as
        # `merged["lh_version"]` did. The version of the document is a
        # property of the document, not a hook entry, so it is written next
        # to `hooks`, not inside it.
        settings["lh_version"] = __version__
        # Declared, not inferred: the next deploy asks the file which launcher
        # wrote these commands instead of asking the config which launchers it
        # currently names. Retiring a binary from the config must not turn the
        # harness's own entries into another tool's.
        settings[SETTINGS_BINARY_KEY] = binary
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
