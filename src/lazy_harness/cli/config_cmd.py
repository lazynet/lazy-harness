"""lh config — interactive wizards for optional features (per ADR-018, ADR-026)."""

from __future__ import annotations

import click

from lazy_harness.core.paths import config_file
from lazy_harness.wizards.knowledge import wizard_knowledge
from lazy_harness.wizards.memory import wizard_memory


@click.group("config")
def config() -> None:
    """Configure optional features interactively."""


@config.command("memory")
@click.option("--init", is_flag=True, help="Run the interactive [memory] wizard.")
def memory_cmd(init: bool) -> None:
    """Configure episodic memory backends ([memory] section)."""
    if not init:
        click.echo("Usage: lh config memory --init")
        return
    wizard_memory(config_file())


@config.command("knowledge")
@click.option("--init", is_flag=True, help="Run the interactive [knowledge] wizard.")
def knowledge_cmd(init: bool) -> None:
    """Configure knowledge backends ([knowledge] section)."""
    if not init:
        click.echo("Usage: lh config knowledge --init")
        return
    wizard_knowledge(config_file())


@config.command("migrate-knowledge")
@click.option(
    "--root",
    default=None,
    help="Store root to write. Defaults to the built-in default.",
)
def migrate_knowledge_cmd(root: str | None) -> None:
    """Rewrite an old [knowledge] block into the store-root shape."""
    # Resolved through the module so tests (and profile overrides) can redirect it.
    from lazy_harness.core import paths
    from lazy_harness.knowledge.marker import DEFAULT_ROOT
    from lazy_harness.migrate.config_shape import migrate_knowledge_block

    target = paths.config_file()
    try:
        migrate_knowledge_block(target, new_root=root or DEFAULT_ROOT)
    except (FileNotFoundError, OSError, ValueError) as e:
        click.echo(f"Could not migrate {target}: {e}", err=True)
        raise SystemExit(1) from e
    click.echo(f"Migrated [knowledge] in {target}")
