"""Pytest plugin: keep the suite's temp files out of any git checkout.

An agent session exports `TMPDIR=<repo>/tmp`. Left alone, `tmp_path` lands
inside that repo: a test deriving a project key from its fixture finds the
outer repo, and `CLAUDE.md` fixtures under `tmp/pytest-of-*` shadow the
repo's `AGENTS.md`, failing `lh repo instructions` on the checkout itself.

The relocation moves `TMPDIR` rather than passing `--basetemp`: pytest wipes a
given basetemp on every run, while its default temproot keeps numbered,
per-user directories with their own retention.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pytest


def _inside_checkout(path: Path) -> bool:
    resolved = path.resolve()
    return any((p / ".git").exists() for p in (resolved, *resolved.parents))


def relocation_target(
    tempdir: Path, *, basetemp: str | None, candidates: Sequence[Path]
) -> Path | None:
    """Where to move the temp root, or None to leave it where it is."""
    if basetemp is not None or not _inside_checkout(tempdir):
        return None
    return next((c for c in candidates if c.is_dir() and not _inside_checkout(c)), None)


def _platform_candidates() -> list[Path]:
    candidates: list[Path] = []
    if sys.platform == "darwin":
        # The per-user temp dir TMPDIR normally points at; this Python build
        # lacks `os.confstr("CS_DARWIN_USER_TEMP_DIR")`, `getconf` has it.
        proc = subprocess.run(
            ["getconf", "DARWIN_USER_TEMP_DIR"], capture_output=True, text=True, check=False
        )
        if proc.returncode == 0 and proc.stdout.strip():
            candidates.append(Path(proc.stdout.strip()))
    candidates.append(Path("/tmp"))
    return candidates


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    # PYTEST_DEBUG_TEMPROOT outranks TMPDIR in pytest; whoever set it chose.
    if os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        return
    target = relocation_target(
        Path(tempfile.gettempdir()),
        basetemp=config.option.basetemp,
        candidates=_platform_candidates(),
    )
    if target is not None:
        os.environ["TMPDIR"] = str(target)
        tempfile.tempdir = None
