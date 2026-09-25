"""Static check for the portable repository instruction contract (ADR-060).

`AGENTS.md` is the one repository instruction surface. Claude Code reads it
directly when no `CLAUDE.md` shadows it; Codex walks the same parent chain.
Agent-specific notes therefore live in clearly labelled sections of AGENTS.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

CANONICAL_NAME = "AGENTS.md"
APPENDIX_NAME = "CLAUDE.md"

#: Directories that hold other checkouts or third-party trees. Walking them
#: reports the same file once per copy, and reports pairs from other branches.
_SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        ".worktrees",
        "node_modules",
        "vendor",
        "__pycache__",
        "site-packages",
    }
)


@dataclass(frozen=True)
class Finding:
    """One broken expectation, addressed to the file that has to change."""

    path: Path
    code: str
    detail: str


def check_repository(
    root: Path, *, instruction_data: tuple[Path, ...] = (), check_tree: bool = True
) -> list[Finding]:
    """Every way `root` departs from the ADR-060 contract, sorted by path."""
    findings: list[Finding] = []

    if check_tree and not (root / CANONICAL_NAME).is_file():
        findings.append(
            Finding(
                path=Path(CANONICAL_NAME),
                code="missing-agents-md",
                detail=(f"no root {CANONICAL_NAME} exists, so repository rules are not portable"),
            )
        )

    if check_tree:
        cwd = Path.cwd().resolve()
        for directory in _walk(root):
            appendix = directory / APPENDIX_NAME
            if not appendix.is_file():
                continue
            is_data = appendix.relative_to(root) in instruction_data
            is_active = cwd.is_relative_to(directory.resolve())
            if is_data and directory != root and not is_active:
                continue
            findings.append(
                Finding(
                    path=appendix.relative_to(root),
                    code="claude-md-shadows-agents",
                    detail=(
                        f"{APPENDIX_NAME} prevents Claude Code from walking the parent "
                        f"{CANONICAL_NAME} chain"
                    ),
                )
            )

    findings.extend(_ancestor_findings(root))

    return sorted(findings, key=lambda f: (f.path.as_posix(), f.code))


def _ancestor_findings(root: Path) -> list[Finding]:
    """`CLAUDE.md` files above `root` that switch Claude Code off `AGENTS.md`.

    Measured on 2.1.280: any `CLAUDE.md` or `.claude/CLAUDE.md` in an ancestor
    of the cwd stops the repository `AGENTS.md` loading, from the root and from
    nested directories alike. A `~/.claude` link to a profile does this to every
    repository under `$HOME`. Reported by absolute path: it is outside the tree.
    """
    findings: list[Finding] = []
    for ancestor in root.resolve().parents:
        findings.extend(shadows_in(ancestor))
    return findings


def shadows_in(directory: Path) -> list[Finding]:
    """The `CLAUDE.md` files `directory` would impose on every repo below it.

    `lh doctor` calls this on `$HOME`, the one ancestor every repository shares,
    so a machine is flagged even when no repository gate runs on it.
    """
    return [
        Finding(
            path=candidate,
            code="ancestor-claude-md-shadows-agents",
            detail=(
                f"an ancestor {APPENDIX_NAME} stops Claude Code loading "
                f"the repository {CANONICAL_NAME} below it"
            ),
        )
        for candidate in (directory / APPENDIX_NAME, directory / ".claude" / APPENDIX_NAME)
        if candidate.is_file()
    ]


def _walk(root: Path) -> list[Path]:
    """Directories under `root`, skipping hidden and vendored trees."""
    found: list[Path] = []
    for current, dirnames, _ in os.walk(root):
        # A `.git` entry below the root marks another checkout (Claude Code's
        # `.claude/worktrees/*`, a submodule): its files belong to another branch.
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _SKIPPED_DIRS and not (Path(current) / name / ".git").exists()
        ]
        found.append(Path(current))
    return found
