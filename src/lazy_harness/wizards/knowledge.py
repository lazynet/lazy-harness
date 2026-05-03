"""Interactive wizard for [knowledge.structure] (lh config knowledge --init)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click
import tomli_w

from lazy_harness.knowledge import graphify
from lazy_harness.wizards._toml_merge import merge_into_config


def wizard_knowledge(
    config_path: Path,
    *,
    prompt_confirm: Callable[[str, bool], bool] = click.confirm,
    echo: Callable[[str], None] = click.echo,
) -> bool:
    """Run the [knowledge.structure] wizard for Graphify. Returns True if written."""
    echo("Graphify — code structure index (tree-sitter knowledge graph).")
    echo("")

    installed = graphify.is_graphify_available()
    if not installed:
        echo("⚠ Graphify is not installed.")
        echo("  Install with `pip install graphify` or your preferred package manager.")
        echo(f"  Pinned version: {graphify.PINNED_VERSION}")
        echo("")
        if not prompt_confirm(
            "Continue setup anyway (settings activate when Graphify is installed)?",
            False,
        ):
            echo("Cancelled.")
            return False
        echo("")

    enabled = prompt_confirm("Enable Graphify MCP server in profiles?", True)
    auto_rebuild = (
        prompt_confirm(
            "Auto-rebuild graph on each git commit (post-commit hook)?",
            False,
        )
        if enabled
        else False
    )

    new_block = {
        "knowledge": {
            "structure": {
                "engine": "graphify",
                "enabled": enabled,
                "auto_rebuild_on_commit": auto_rebuild,
                "version": graphify.PINNED_VERSION,
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
