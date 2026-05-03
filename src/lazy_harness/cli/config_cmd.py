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
