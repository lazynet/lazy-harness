"""lh repo — checks on a repository's own instruction files."""

from __future__ import annotations

from pathlib import Path

import click

from lazy_harness.core.repo_instructions import (
    APPENDIX_NAME,
    CANONICAL_NAME,
    Finding,
    check_repository,
)


@click.group()
def repo() -> None:
    """Repository instruction contracts."""


@repo.command("instructions")
@click.argument(
    "paths",
    nargs=-1,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def instructions(paths: tuple[Path, ...]) -> None:
    """Check that AGENTS.md is the only repository instruction surface.

    Takes any number of repositories (default: the working directory), so one
    run can gate a whole fleet; exits 1 if any of them has a finding.
    """
    targets = paths or (Path("."),)
    total = 0
    for target in targets:
        findings = check_repository(target)
        total += len(findings)
        if len(targets) == 1:
            _report_single(findings)
        else:
            _report_one_of_many(target, findings)

    if total:
        click.echo(
            f"\n{total} finding(s). Keep all repository instructions in "
            f"{CANONICAL_NAME}; {APPENDIX_NAME} shadows it for Claude Code sessions."
        )
        raise SystemExit(1)


def _report_single(findings: list[Finding]) -> None:
    if not findings:
        click.echo(f"✓ {CANONICAL_NAME} is the portable repository contract")
    for finding in findings:
        click.echo(f"✗ {finding.path.as_posix()}: {finding.code} — {finding.detail}")


def _report_one_of_many(target: Path, findings: list[Finding]) -> None:
    if not findings:
        click.echo(f"✓ {target}")
        return
    click.echo(f"✗ {target}")
    for finding in findings:
        click.echo(f"    {finding.path.as_posix()}: {finding.code} — {finding.detail}")
