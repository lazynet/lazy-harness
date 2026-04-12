"""Deploy orchestration — symlinks profiles, hooks, skills."""

from __future__ import annotations

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
