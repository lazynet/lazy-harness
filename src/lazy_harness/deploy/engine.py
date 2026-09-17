"""Deploy orchestration — symlinks profiles, hooks, skills."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Collection
from pathlib import Path

import click

from lazy_harness.agents.base import ConfigPlanner, HookEntry, WriteOp
from lazy_harness.agents.registry import (
    DEFAULT_HARNESS_BINARY,
    agent_for_profile,
    binary_for_profile,
)
from lazy_harness.core.config import Config, ProfileEntry
from lazy_harness.core.paths import config_dir, expand_path
from lazy_harness.deploy.symlinks import ensure_symlink
from lazy_harness.hooks.loader import HookInfo
from lazy_harness.hooks.signal_gaps import HookSignalGap

# The launcher invocation every generated builtin command takes. `hook_command`
# builds it; the classifier that recognises it lives with the merge, in the
# adapter. The launcher itself is per profile since decision 11 —
# `DEFAULT_HARNESS_BINARY` is only what a profile that declares nothing gets.
_HOOK_SUBCOMMAND = "hook"


class ConfigPlannerRequiredError(TypeError):
    """A profile's adapter cannot plan its own config documents.

    Raised before anything is written. Merging is an adapter operation because
    parsing never was agent-neutral (decision 4, 2026-09-13 multi-agent design),
    so an adapter that has not been taught its own format has nothing the engine
    could write on its behalf — and discovering that halfway through a deploy
    would leave the profiles before it already written.
    """

    def __init__(self, profile: str, agent_name: str) -> None:
        self.profile = profile
        self.agent_name = agent_name
        super().__init__(
            f"Profile '{profile}' runs agent '{agent_name}', which cannot plan its "
            f"own config documents. Deploy is refused rather than half-applied."
        )


class ConfigTargetChangedError(RuntimeError):
    """A config target moved between the engine reading it and applying the plan.

    Atomic replace is not concurrency control: a rename prevents a half-written
    file, it does not prevent losing an approval the agent wrote *after* the read
    (decision 4, 2026-09-13 multi-agent design). Both Codex and Copilot were
    observed writing their own config mid-session — Codex persists
    `[projects.*]` trust and `[hooks.state]` into `config.toml`, Copilot writes
    `permissions-config.json` as the user approves things.

    The conservative option is taken deliberately. A lock would have to be
    honoured by the agents, which do not know the harness exists; winning the
    race silently would destroy decisions the user made by hand, and there is no
    test written against a fixture that would catch it. Deploying while an agent
    is running is not a supported state, so it is refused rather than resolved.
    """

    def __init__(self, profile: str, changed: list[Path]) -> None:
        self.profile = profile
        self.changed = changed
        listed = ", ".join(str(path) for path in changed)
        super().__init__(
            f"Config changed underneath this deploy in profile {profile!r}: {listed}. "
            f"The agent writing them is most likely still running — close it and "
            f"re-run. Nothing was written."
        )


class UnknownProfileError(ValueError):
    """`--profile` named a profile the config does not declare.

    Raised rather than silently deploying nothing: `lh deploy --profile <typo>`
    that exits 0 having written nothing is indistinguishable, to the step 4
    contract gate, from a deploy that worked.
    """

    def __init__(self, name: str, known: Collection[str]) -> None:
        self.name = name
        self.known = sorted(known)
        listed = ", ".join(self.known) if self.known else "none"
        super().__init__(f"Unknown profile '{name}'. Configured profiles: {listed}")


def selected_profiles(cfg: Config, only: str | None) -> dict[str, ProfileEntry]:
    """The profiles one deploy touches — every one, or just the named one.

    The single importable place that answers it. `deploy/snapshot.py` reads it
    too: narrowing the deploy in the engine loops while the snapshot still
    walked every profile would take a manifest listing artifacts this deploy
    never writes, and a later `--rollback` would restore another profile's files
    from a snapshot that had no business capturing them.
    """
    if only is None:
        return cfg.profiles.items
    entry = cfg.profiles.items.get(only)
    if entry is None:
        raise UnknownProfileError(only, cfg.profiles.items)
    return {only: entry}


def deploys_global_link(cfg: Config, only: str | None) -> bool:
    """Whether this deploy may touch the agent's global config link.

    The link is global but its *target* is the default profile's config dir, so
    it is an artifact of that profile and of no other. A narrowed deploy of the
    default profile leaves it correct; a narrowed deploy of any other profile
    that rewrote it would reach outside the blast-radius boundary `--profile`
    exists to draw — which is precisely what the step 4 gate, running against a
    throwaway profile, must not do to `~/.claude`.
    """
    return only is None or only == cfg.profiles.default


def hook_command(hook: HookInfo, *, profile: str, binary: str = DEFAULT_HARNESS_BINARY) -> str:
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


def deploy_profiles(cfg: Config, *, only: str | None = None) -> None:
    """Deploy profile content as symlinks to agent config dirs.

    `only` narrows the loop to one profile; `None` is every profile, which is
    what `lh deploy` without `--profile` still does.
    """
    profiles_src = config_dir() / "profiles"
    if not profiles_src.is_dir():
        click.echo("No profiles directory found. Run: lh init")
        return

    for name, entry in selected_profiles(cfg, only).items():
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


def _report_omitted(
    script_names: list[str],
    event: str,
    profile: str,
    undeliverable: dict[tuple[str, str], HookSignalGap],
) -> list[str]:
    """Drop the hooks this agent cannot feed, naming each one as it goes.

    The naming is the point, not a courtesy. A hook that vanishes from a deploy
    without a word is the same class of defect as the one this filter removes —
    a silence the operator cannot distinguish from a hook that installed and
    stayed quiet. Swapping one silence for the other would be no fix at all, so
    the omission is a line of output before it is an absence in the artifact.

    Printed per event rather than once per profile because a hook wired to two
    events is omitted from both, and collapsing that to one line would leave the
    second event looking untouched.
    """
    kept: list[str] = []
    for name in script_names:
        gap = undeliverable.get((event, name))
        if gap is None:
            kept.append(name)
            continue
        missing = ", ".join(signal.value for signal in gap.missing)
        click.echo(
            f"  · {gap.hook} omitted in '{profile}': agent '{gap.agent}' does not deliver {missing}"
        )
    return kept


def _report_renamed(script_names: list[str]) -> None:
    """Name the rename, once per alias found in a profile's config.

    The alias itself keeps deploying (`resolve_script_names` resolves it same
    as the canonical key), so this is a nudge rather than a gate: the operator
    can move at their own pace, but not without being told there is a move to
    make.
    """
    from lazy_harness.hooks.loader import alias_target

    for name in script_names:
        canonical = alias_target(name)
        if canonical is not None:
            click.echo(f"  · hook '{name}' is now '{canonical}'; rename it in config.toml")


def _hook_entries_for(cfg: Config, profile: str, binary: str) -> dict[str, list[HookEntry]]:
    """The hook entries one profile's config gets, as agent-neutral records.

    Built per profile because `hook_command` names the profile and takes its
    binary: a single shared list would deploy every profile's hooks under
    whichever one happened to be generated first.

    Third-party commands declared in config are emitted to every profile, so a
    tool's hooks stop depending on which profile its installer happened to run
    against. Appended after the harness scripts, including on events whose
    scripts list is empty.

    A hook whose declared `Signal`s this profile's agent cannot deliver is left
    out, and said out loud. `BuiltinHookSpec.signals` was introduced precisely
    so `stop-verify-guard` could not install on such an agent, run, find no goal
    marker, conclude there was nothing to verify and pass — green because it
    cannot fail. Until this filter existed only `lh doctor` knew, and it knew
    after the fact. The gap itself is `gaps_for_profile`'s answer, not a second
    reading of the same fields here: doctor reports what deploy acts on, and the
    two would drift the first time either learned something new.
    """
    from lazy_harness.deploy.defaults import merge_with_defaults
    from lazy_harness.hooks.loader import resolve_script_names
    from lazy_harness.hooks.signal_gaps import gaps_for_profile

    agent = agent_for_profile(cfg, profile)
    effective = merge_with_defaults(cfg.hooks, agent)
    undeliverable = {(gap.event, gap.hook): gap for gap in gaps_for_profile(cfg, profile)}

    entries: dict[str, list[HookEntry]] = {}
    for event_name, script_names in effective.items():
        script_names = _report_omitted(script_names, event_name, profile, undeliverable)
        _report_renamed(script_names)
        if not script_names:
            continue
        hooks = resolve_script_names(script_names, event=event_name)
        if not hooks:
            continue
        entries[event_name] = [
            HookEntry(
                command=hook_command(hook, profile=profile, binary=binary),
                matcher=hook.matcher,
            )
            for hook in hooks
        ]

    for event_name, event_cfg in cfg.hooks.items():
        for ext in event_cfg.external:
            entries.setdefault(event_name, []).append(
                HookEntry(command=ext.command, matcher=ext.matcher)
            )
    return entries


def _planner_for(cfg: Config, profile: str) -> ConfigPlanner:
    """The profile's adapter, refused unless it can plan its own config.

    Refused here rather than mid-deploy, which is what the `ConfigPlanner`
    docstring asks for: `deploy_config` resolves every selected profile's planner
    before it writes anything, so a config naming one adapter that cannot plan
    does not leave the other profiles half-deployed.
    """
    agent = agent_for_profile(cfg, profile)
    if not isinstance(agent, ConfigPlanner):
        raise ConfigPlannerRequiredError(profile, agent.name)
    return agent


def _stamp(path: Path) -> tuple[int, int] | None:
    """A target's identity for the race check: `(mtime_ns, size)`, or `None`.

    Both halves are compared because neither is sufficient alone. Size misses an
    in-place edit of the same length — Codex flipping one `trust_level` value is
    exactly that shape — and mtime misses a write that lands inside one
    filesystem timestamp tick, which is a second on any filesystem with
    one-second resolution.

    `None` means "was not a file", and it is a value rather than an omission so
    that absent-then-present compares unequal: the read pass skips a target that
    does not exist, so a file the agent creates mid-deploy is the one case where
    the engine plans against no prior content at all.
    """
    if not path.is_file():
        return None
    info = path.stat()
    return (info.st_mtime_ns, info.st_size)


def _read_targets(
    planner: ConfigPlanner, target_dir: Path
) -> tuple[dict[Path, str], dict[Path, tuple[int, int] | None]]:
    """Step 2 of the cycle: read every target that exists, stamping all of them.

    The stamp covers targets that do *not* exist as well as the ones read, which
    is why it is taken here rather than derived from `existing`.
    """
    existing: dict[Path, str] = {}
    stamps: dict[Path, tuple[int, int] | None] = {}
    for target in planner.config_targets():
        path = target_dir / target
        stamps[target] = _stamp(path)
        if path.is_file():
            existing[target] = path.read_text()
    return existing, stamps


def _refuse_if_changed(
    stamps: dict[Path, tuple[int, int] | None], target_dir: Path, profile: str
) -> None:
    """Abort the whole plan if any target moved since it was read.

    Whole-plan, not per-op: `settings.json` and `.claude.json` come back from one
    `plan_config` call, and a check inside `_apply` would write the first before
    discovering that the second had been edited underneath it.
    """
    changed = [target for target, stamp in stamps.items() if _stamp(target_dir / target) != stamp]
    if changed:
        raise ConfigTargetChangedError(profile, sorted(changed))


def _report_lines(label: str, items: list[str]) -> None:
    """Render one diagnostic group.

    Column width and truncation live here, not in the adapter: the adapter emits
    flat `"<label>: <detail>"` strings and knows nothing about a terminal.
    """
    for item in items:
        head, _, detail = item.partition(": ")
        click.echo(f"      {head:<20} {detail[:60]}")


def _apply(op: WriteOp, target_dir: Path, profile: str) -> None:
    """Perform one planned write or delete, and report what the plan diagnosed."""
    path = target_dir / op.relative_path
    label = f"{profile}/{op.relative_path}"

    if op.repaired:
        # The backup is I/O, so it is the engine's; the adapter only reports the
        # repair. Claude Code discards the whole settings file on one bad field,
        # so the pre-merge bytes are worth keeping even though the merge fixed it.
        if path.is_file():
            path.with_suffix(path.suffix + ".bak").write_text(path.read_text())
        click.echo(
            f"  ⚠  {label}: repaired {len(op.repaired)} "
            f"{_plural(len(op.repaired), 'entry', 'entries')} the agent would reject "
            f"(the whole file is discarded on one bad field); "
            f"backup saved to {path.name}.bak."
        )
        _report_lines("repaired", op.repaired)

    if op.preserved:
        click.echo(
            f"  ·  {label}: preserved {len(op.preserved)} "
            f"{_plural(len(op.preserved), 'entry', 'entries')} not managed by the harness."
        )
        _report_lines("preserved", op.preserved)

    if op.dropped:
        click.echo(
            f"  ·  {label}: dropped {len(op.dropped)} harness "
            f"{_plural(len(op.dropped), 'entry', 'entries')} no longer generated."
        )
        _report_lines("dropped", op.dropped)

    if op.artifact is None:
        if path.exists():
            path.unlink()
            click.echo(f"  ✓ {label} (removed — no longer generated)")
        return

    # Written verbatim. Producing the text is the adapter's half of decision 4;
    # reserialising it here would be the engine learning the format again.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(op.artifact.content)
    click.echo(f"  ✓ {label}")


def deploy_config(cfg: Config, *, only: str | None = None) -> None:
    """Deploy every profile's native config documents: discover, read, plan, apply.

    The cycle decision 4 of the 2026-09-13 multi-agent design prescribes. The
    adapter names its targets and merges them; the engine reads, writes, deletes
    and prints. One `plan_config` call per profile, so an adapter whose hooks and
    MCP servers share a file emits a single write for it and cannot overwrite its
    own earlier result.

    `only` narrows it to one profile through `selected_profiles`, exactly as the
    other deploy steps are narrowed.
    """
    profiles = selected_profiles(cfg, only)
    # Resolved for every selected profile before the first write: an adapter that
    # cannot plan is a refusal, not a partial deploy.
    planners = {name: _planner_for(cfg, name) for name in profiles}

    servers = _collect_mcp_servers(cfg)

    for name, entry in profiles.items():
        planner = planners[name]
        target_dir = expand_path(entry.config_dir)
        binary = binary_for_profile(cfg, name)

        existing, stamps = _read_targets(planner, target_dir)

        ops = planner.plan_config(
            _hook_entries_for(cfg, name, binary), servers, existing, binary=binary
        )
        if not ops:
            click.echo(f"  · {name}: nothing to deploy.")
            continue

        _refuse_if_changed(stamps, target_dir, name)
        target_dir.mkdir(parents=True, exist_ok=True)
        for op in ops:
            _apply(op, target_dir, name)


def deploy_hooks(cfg: Config, *, only: str | None = None) -> None:
    """Deploy only the hook half of each profile's config.

    A narrowing of `deploy_config`, kept because the byte-identity acceptance
    test for the `ConfigPlanner` move is written against this entry point. Every
    planner treats an empty `servers` as "no MCP document to write", so this
    reaches exactly the files hooks live in.
    """
    _deploy_config_subset(cfg, only=only, hooks=True, servers=False)


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


def deploy_mcp_servers(cfg: Config, *, only: str | None = None) -> None:
    """Deploy only the MCP half of each profile's config.

    The counterpart of `deploy_hooks`, and kept for the same reason.
    """
    _deploy_config_subset(cfg, only=only, hooks=False, servers=True)


def _deploy_config_subset(cfg: Config, *, only: str | None, hooks: bool, servers: bool) -> None:
    """Run the cycle with one half of the inputs blanked out.

    Blanking an input rather than filtering the resulting ops is what makes the
    two halves independent: a planner asked to plan with no hooks returns no
    settings write at all, which is not the same as a write of an empty hooks
    block — the latter would uninstall every foreign entry on a profile that
    configures no harness hooks.
    """
    profiles = selected_profiles(cfg, only)
    planners = {name: _planner_for(cfg, name) for name in profiles}
    detected = _collect_mcp_servers(cfg) if servers else {}

    for name, entry in profiles.items():
        planner = planners[name]
        target_dir = expand_path(entry.config_dir)
        binary = binary_for_profile(cfg, name)

        existing, stamps = _read_targets(planner, target_dir)
        entries = _hook_entries_for(cfg, name, binary) if hooks else {}

        ops = planner.plan_config(entries, detected, existing, binary=binary)
        if not ops:
            continue

        _refuse_if_changed(stamps, target_dir, name)
        target_dir.mkdir(parents=True, exist_ok=True)
        for op in ops:
            _apply(op, target_dir, name)


def deploy_claude_symlink(cfg: Config, *, only: str | None = None) -> None:
    """Create the agent's global config symlink to the default profile's config dir.

    Skipped when `only` names a profile that is not the default — see
    `deploys_global_link` for why the link belongs to that profile alone.

    The link and its target both belong to the default profile, so the agent
    asked for it is that profile's, not `[agent].type`. An adapter answering
    `None` is refusing to own a global link at all, and that refusal is the last
    thing standing between a narrowed deploy and a live link: the step 4 gate
    made a Codex throwaway the default and watched `~/.claude` — the `lazy`
    profile's own link — repointed at the throwaway's Codex home, because the
    resolution here never asked the adapter that returns `None` to prevent it.
    """
    from lazy_harness.agents.registry import agent_for_profile

    if not deploys_global_link(cfg, only):
        click.echo(f"  · skipped — '{only}' is not the default profile")
        return

    agent = agent_for_profile(cfg, cfg.profiles.default)
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
