"""lh repo — checks on a repository's own instruction files."""

from __future__ import annotations

from pathlib import Path

import click

from lazy_harness.core.repo_instructions import (
    APPENDIX_NAME,
    CANONICAL_NAME,
    check_repository,
)


@click.group()
def repo() -> None:
    """Repository instruction contracts."""


@repo.command("instructions")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=".",
)
def instructions(path: Path) -> None:
    """Check that AGENTS.md is the only repository instruction surface."""
    findings = check_repository(path)

    if not findings:
        click.echo(f"✓ {CANONICAL_NAME} is the portable repository contract")
        return

    for finding in findings:
        click.echo(f"✗ {finding.path.as_posix()}: {finding.code} — {finding.detail}")
    click.echo(
        f"\n{len(findings)} finding(s). Keep all repository instructions in "
        f"{CANONICAL_NAME}; {APPENDIX_NAME} shadows it for nested Claude Code sessions."
    )
    raise SystemExit(1)
