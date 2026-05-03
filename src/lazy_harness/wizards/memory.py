"""Interactive wizard for [memory.engram] (lh config memory --init)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click
import tomli_w

from lazy_harness.memory import engram
from lazy_harness.wizards._toml_merge import merge_into_config


def wizard_memory(
    config_path: Path,
    *,
    prompt_confirm: Callable[[str, bool], bool] = click.confirm,
    echo: Callable[[str], None] = click.echo,
) -> bool:
    """Run the [memory.engram] wizard. Returns True if config was written."""
    echo("Engram — episodic memory backend (per-project agent diary).")
    echo("")

    installed = engram.is_engram_available()
    if not installed:
        echo("⚠ Engram is not installed.")
        echo("  Install with your package manager (e.g. `brew install engram`).")
        echo(f"  Pinned version: {engram.PINNED_VERSION}")
        echo("")
        if not prompt_confirm(
            "Continue setup anyway (settings activate when Engram is installed)?",
            False,
        ):
            echo("Cancelled.")
            return False
        echo("")

    enabled = prompt_confirm("Enable Engram MCP server in profiles?", True)
    git_sync = (
        prompt_confirm(
            "Use git sync for memory chunks (.engram/chunks/ committed per repo)?",
            True,
        )
        if enabled
        else False
    )
    cloud = (
        prompt_confirm(
            "Enable Engram cloud sync (opt-in, breaks local-first guarantee)?",
            False,
        )
        if enabled
        else False
    )

    new_block = {
        "memory": {
            "engram": {
                "enabled": enabled,
                "git_sync": git_sync,
                "cloud": cloud,
                "version": engram.PINNED_VERSION,
            }
        }
    }

    echo("")
    echo(f"Will write to {config_path}:")
    echo("")
    echo(tomli_w.dumps(new_block))

    if not prompt_confirm("Write this block to your config?", True):
        echo("Cancelled.")
        return False

    merge_into_config(config_path, new_block)
    echo(f"✓ Updated {config_path}")
    return True
