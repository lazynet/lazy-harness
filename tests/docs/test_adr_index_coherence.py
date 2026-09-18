"""Deterministic coherence check: the ADR index matches the files on disk.

The README is the browsable inventory of decisions, while each ADR file owns
its status.  Checking both directions keeps a new file from being invisible,
a removed file from leaving a dead link, and the index status from drifting
away from its source of truth.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
ADR_DIR = REPO_ROOT / "specs" / "adrs"
ADR_INDEX = ADR_DIR / "README.md"

_INDEX_ROW = re.compile(
    r"^\| \[(\d{3})\]\(\./([^\s)]+)\) \|\s*(\w+)",
    re.MULTILINE,
)
_ADR_STATUS = re.compile(r"^\*\*Status:\*\*\s+(\w+)", re.MULTILINE)


def _adr_files() -> set[str]:
    return {path.name for path in ADR_DIR.glob("[0-9][0-9][0-9]-*.md")}


def _index_rows() -> list[tuple[str, str]]:
    index_text = ADR_INDEX.read_text(encoding="utf-8")
    return [(target, status.strip()) for _number, target, status in _INDEX_ROW.findall(index_text)]


def test_every_adr_file_has_an_index_row() -> None:
    indexed_files = {target for target, _status in _index_rows()}
    missing = sorted(_adr_files() - indexed_files)

    assert not missing, f"ADR index is missing files: {', '.join(missing)}"


def test_every_index_row_targets_an_existing_file() -> None:
    dangling = sorted(
        target for target, _status in _index_rows() if not (ADR_DIR / target).is_file()
    )

    assert not dangling, f"ADR index has dangling rows: {', '.join(dangling)}"


def test_every_index_status_matches_its_adr_file() -> None:
    mismatches: list[str] = []
    for target, index_status in _index_rows():
        adr_path = ADR_DIR / target
        if not adr_path.is_file():
            continue
        status_match = _ADR_STATUS.search(adr_path.read_text(encoding="utf-8"))
        file_status = status_match.group(1) if status_match is not None else "<missing>"
        if index_status != file_status:
            mismatches.append(f"{target}: index says {index_status}, file says {file_status}")

    assert not mismatches, "ADR status mismatches: " + "; ".join(mismatches)
