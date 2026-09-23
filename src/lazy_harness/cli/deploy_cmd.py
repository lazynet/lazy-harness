"""lh deploy — deploy profiles, hooks, skills."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape

from lazy_harness.agents.registry import get_agent
from lazy_harness.cli.profile_cmd import render_sync_results
from lazy_harness.core.backups import (
    DEPLOY_NAMESPACE,
    backups_root,
    latest_backup_dir,
    namespace_dir,
    prune_backups,
)
from lazy_harness.core.config import Config, ConfigError, load_config
from lazy_harness.core.paths import config_dir, config_file
from lazy_harness.core.sync_agent_md import SyncError, sync_profiles
from lazy_harness.deploy.engine import (
    ConfigPlannerRequiredError,
    UnknownProfileError,
    deploy_claude_symlink,
    deploy_config,
    deploy_profiles,
    repair_plugin_registries,
    selected_profiles,
)
from lazy_harness.deploy.skills import SkillCollisionError, SkillLedgerError
from lazy_harness.deploy.snapshot import snapshot_targets, take_snapshot
from lazy_harness.migrate.rollback import apply_rollback_log

# Ten snapshots of a ~135 KB artifact set cost about 1.35 MB. Pruning by count
# keeps the cheap operation cheap without a condition that could decide wrong.
KEEP_SNAPSHOTS = 10


def _sync_system_docs(cfg: Config, *, only: str | None = None) -> None:
    profiles_dir = config_dir() / "profiles"
    if not profiles_dir.is_dir():
        click.echo("No profile dirs found.")
        return

    results = sync_profiles(profiles_dir, get_agent(cfg.agent.type), cfg=cfg, only=only)
    if not results:
        click.echo("No profile dirs found.")
        return
    render_sync_results(results, Console())


def _take_snapshot(cfg: Config, only: str | None = None) -> Path:
    """Record the pre-deploy state of every managed artifact.

    Unconditional: a version-change or plan-diff trigger is an optimisation of
    an operation that is already cheap, and each condition can be wrong in the
    direction of no snapshot when one was needed.
    """
    root = backups_root()
    # Microseconds, not seconds: two deploys inside one second would resolve to
    # one directory, and the second `take_snapshot` would overwrite the first
    # one's manifest with post-deploy state. Still lexically ordered, which is
    # what `latest_backup_dir` and the prune both sort on.
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S.%f")
    snapshot_dir = namespace_dir(root, DEPLOY_NAMESPACE) / stamp
    take_snapshot(snapshot_targets(cfg, only=only), snapshot_dir)
    prune_backups(root, DEPLOY_NAMESPACE, keep=KEEP_SNAPSHOTS)
    return snapshot_dir


def _run_deploy(cfg: Config, only: str | None = None) -> None:
    scope = f" ({only})" if only else ""
    click.echo(f"=== lazy-harness deploy{scope} ===\n")

    click.echo("Syncing system docs:")
    try:
        _sync_system_docs(cfg, only=only)
    except SyncError as e:
        click.echo(f"Error: {escape(str(e))}", err=True)
        raise SystemExit(1) from e
    click.echo()

    click.echo("Deploying profiles:")
    # Restoring a link displaces whatever regular file sat in its place, so the
    # profile half hands the config half the contents it took out of the way.
    # Without that, the merge reads the freshly re-linked source and another
    # tool's hooks are gone with no line in `preserved` or `dropped` to say so.
    displaced = deploy_profiles(cfg, only=only)
    click.echo()

    # One step, not two: hooks and MCP servers are planned together so an
    # adapter whose documents overlap writes each of them once (decision 4,
    # 2026-09-13 multi-agent design).
    click.echo("Deploying agent config:")
    deploy_config(cfg, only=only, displaced=displaced)
    click.echo()

    click.echo("Setting up ~/.claude symlink:")
    deploy_claude_symlink(cfg, only=only)
    click.echo()

    click.echo("Repairing plugin registry paths:")
    repair_plugin_registries(cfg, only=only)
    click.echo()

    click.echo("Done.")


@click.command("deploy")
@click.option(
    "--snapshot",
    "snapshot_only",
    is_flag=True,
    help="Snapshot the managed artifacts and exit without deploying. "
    "Every deploy snapshots anyway; this only skips the deploy.",
)
@click.option(
    "--rollback",
    "rollback",
    is_flag=True,
    help="Restore the managed artifacts from the most recent deploy snapshot.",
)
@click.option(
    "--profile",
    "profile",
    default=None,
    metavar="NAME",
    help="Deploy only this profile. Its symlinks, hooks and MCP servers are "
    "written and no other profile is touched; the agent's global config link "
    "follows only when NAME is the default profile.",
)
def deploy(snapshot_only: bool, rollback: bool, profile: str | None) -> None:
    """Deploy profiles, hooks, and skills."""
    if snapshot_only and rollback:
        click.echo("Error: --snapshot and --rollback are mutually exclusive.", err=True)
        raise SystemExit(1)

    # A snapshot's manifest already records the scope it was taken at. Replaying
    # a subset of it would restore fewer artifacts than the snapshot captured
    # and still report a rollback, so the narrowing is refused rather than
    # silently ignored.
    if rollback and profile is not None:
        click.echo("Error: --profile and --rollback are mutually exclusive.", err=True)
        raise SystemExit(1)

    if rollback:
        latest = latest_backup_dir(backups_root(), DEPLOY_NAMESPACE)
        if latest is None:
            click.echo("No deploy snapshot found to roll back.", err=True)
            raise SystemExit(1)
        click.echo(f"Rolling back using {latest}")
        for message in apply_rollback_log(latest):
            click.echo(f"  {message}")
        click.echo("Rollback complete.")
        return

    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    # Validated before the snapshot: a typo must cost nothing, and a snapshot
    # taken for a profile that does not exist has no artifacts to record.
    try:
        selected_profiles(cfg, profile)
    except UnknownProfileError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e

    try:
        snapshot_dir = _take_snapshot(cfg, profile)
        click.echo(f"Snapshot: {snapshot_dir}\n")
        if snapshot_only:
            return
        _run_deploy(cfg, profile)
    except (ConfigPlannerRequiredError, SkillCollisionError, SkillLedgerError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1) from e
