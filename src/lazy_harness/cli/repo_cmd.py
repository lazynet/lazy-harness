"""lh repo — checks on a repository's own instruction files."""

from __future__ import annotations

import json
from dataclasses import dataclass
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
@click.option("--manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument(
    "paths",
    nargs=-1,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def instructions(paths: tuple[Path, ...], manifest: Path | None) -> None:
    """Check that AGENTS.md is the only repository instruction surface.

    Takes any number of repositories (default: the working directory), so one
    run can gate a whole fleet; exits 1 if any of them has a finding.
    """
    if manifest is not None and paths:
        raise click.UsageError("--manifest cannot be combined with repository paths")
    entries = (
        _load_manifest(manifest)
        if manifest is not None
        else [
            RepositoryEntry(path=path, status="active", instruction_data=())
            for path in (paths or (Path("."),))
        ]
    )
    total = 0
    for entry in entries:
        findings = check_repository(
            entry.path,
            instruction_data=entry.instruction_data,
            check_tree=entry.status == "active",
        )
        total += len(findings)
        if manifest is not None:
            click.echo(f"{entry.status}: {entry.path}")
        if len(entries) == 1 and manifest is None:
            _report_single(findings)
        else:
            _report_one_of_many(entry.path, findings)

    if total:
        click.echo(
            f"\n{total} finding(s). Keep all repository instructions in "
            f"{CANONICAL_NAME}; {APPENDIX_NAME} shadows it for Claude Code sessions."
        )
        raise SystemExit(1)


@dataclass(frozen=True)
class RepositoryEntry:
    path: Path
    status: str
    instruction_data: tuple[Path, ...]


def _load_manifest(path: Path) -> list[RepositoryEntry]:
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise click.BadParameter(f"invalid manifest: {exc}", param_hint="--manifest") from exc
    if not isinstance(document, dict) or set(document) != {"repositories"}:
        raise click.BadParameter("invalid manifest object", param_hint="--manifest")
    rows = document["repositories"]
    if not isinstance(rows, list) or not rows:
        raise click.BadParameter("invalid repositories list", param_hint="--manifest")
    base = path.resolve().parent
    entries: list[RepositoryEntry] = []
    seen: set[Path] = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not {"path", "status"} <= set(row)
            or set(row) - {"path", "status", "instruction_data"}
        ):
            raise click.BadParameter("invalid repository entry", param_hint="--manifest")
        status = row["status"]
        if status not in ("active", "deferred", "upstream"):
            raise click.BadParameter(f"invalid status: {status!r}", param_hint="--manifest")
        root = _safe_path(base, row["path"])
        if not root.is_dir() or root in seen:
            raise click.BadParameter(
                f"invalid or duplicate repository: {root}", param_hint="--manifest"
            )
        seen.add(root)
        raw_data = row.get("instruction_data", [])
        if not isinstance(raw_data, list):
            raise click.BadParameter("invalid instruction_data list", param_hint="--manifest")
        data: list[Path] = []
        for item in raw_data:
            target = _safe_path(root, item)
            if target == root / APPENDIX_NAME:
                raise click.BadParameter(
                    f"root {APPENDIX_NAME} cannot be instruction_data", param_hint="--manifest"
                )
            if target.name != APPENDIX_NAME or not target.is_file():
                raise click.BadParameter(
                    f"invalid instruction_data file: {item!r}", param_hint="--manifest"
                )
            data.append(target.relative_to(root))
        entries.append(RepositoryEntry(root, status, tuple(data)))
    return entries


def _safe_path(base: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute() or ".." in Path(raw).parts:
        raise click.BadParameter(f"invalid relative path: {raw!r}", param_hint="--manifest")
    try:
        target = (base / raw).resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        raise click.BadParameter(
            f"invalid relative path {raw!r}: {exc}", param_hint="--manifest"
        ) from exc
    if not target.is_relative_to(base):
        raise click.BadParameter(f"invalid path escape: {raw!r}", param_hint="--manifest")
    return target


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
