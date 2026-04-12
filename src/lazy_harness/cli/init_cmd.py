"""lh init — interactive setup wizard."""

from __future__ import annotations

import os
from pathlib import Path

import click
from rich.console import Console

from lazy_harness.core.paths import config_file
from lazy_harness.init.wizard import (
    ExistingSetupError,
    WizardAnswers,
    check_existing_setup,
    run_wizard,
)
from lazy_harness.migrate.detector import detect_qmd


def _home() -> Path:
    return Path(os.path.expanduser("~"))


@click.command("init")
@click.option("--force", is_flag=True, help="Reinitialize, backing up existing config.")
def init(force: bool) -> None:
    """Initialize lazy-harness for a new user."""
    console = Console()
    home = _home()
    cfg = config_file()

    if not force:
        try:
            check_existing_setup(home=home, lh_config=cfg)
        except ExistingSetupError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1) from e

    profile_name = click.prompt("Profile name", default="personal")
    agent = click.prompt("Agent", default="claude-code")
    knowledge_default = str(home / "Documents" / "lazy-harness-knowledge")
    knowledge_path = click.prompt("Knowledge directory", default=knowledge_default)

    enable_qmd = False
    if detect_qmd():
        enable_qmd = click.confirm("QMD detected. Enable knowledge indexing?", default=True)

    answers = WizardAnswers(
        profile_name=profile_name,
        agent=agent,
        knowledge_path=Path(knowledge_path).expanduser(),
        enable_qmd=enable_qmd,
    )
    run_wizard(answers, config_path=cfg)

    console.print(f"[green]✓[/green] Config created at {cfg}")
    console.print(f"[green]✓[/green] Profile '{profile_name}' created")
    console.print(f"[green]✓[/green] Knowledge directory ready at {answers.knowledge_path}")
    if enable_qmd:
        console.print(
            "[green]✓[/green] QMD integration flagged "
            "(run `lh knowledge sync` to initialize)"
        )
    console.print()
    console.print("Run `lh doctor` to verify your setup.")
