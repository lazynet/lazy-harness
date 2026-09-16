"""Deterministic coherence check: the `sync_claude` shim's ADR citation.

`core/sync_claude.py` is a compatibility re-export whose whole payload is one
sentence of prose — the ADR that recorded the rename. That sentence is the only
thing a reader gets, so a wrong number sends them to an unrelated decision and
the shim documents nothing.

The number is not typed here. The ADR that owns the rename is the one carrying
the `### \\`core/sync_claude.py\\` rename` heading, and the docstring must cite
that one. If the section moves to another ADR, this test follows it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
ADR_DIR = REPO_ROOT / "specs" / "adrs"
SHIM = REPO_ROOT / "src" / "lazy_harness" / "core" / "sync_claude.py"

_RENAME_HEADING = re.compile(r"^###\s+`core/sync_claude\.py`\s+rename\s*$", re.MULTILINE)
_ADR_NUMBER = re.compile(r"^(\d{3})-")
_CITED_ADR = re.compile(r"ADR-(\d{3})")


def adrs_recording_the_rename() -> set[str]:
    """The ADR numbers whose body carries the rename section."""
    found: set[str] = set()
    for path in sorted(ADR_DIR.glob("*.md")):
        match = _ADR_NUMBER.match(path.name)
        if match is None:
            continue
        if _RENAME_HEADING.search(path.read_text(encoding="utf-8")):
            found.add(match.group(1))
    return found


def adrs_cited_in(module_text: str) -> set[str]:
    """Every `ADR-NNN` the module's text names."""
    return set(_CITED_ADR.findall(module_text))


def test_the_shim_cites_the_adr_that_actually_records_its_rename() -> None:
    recording = adrs_recording_the_rename()

    # Guards the anchor in both directions: a heading rewrite that drops the
    # section, or a second ADR claiming it, must fail loudly rather than leave
    # this test comparing against an empty or ambiguous set.
    assert len(recording) == 1, (
        f"expected exactly one ADR to record the rename, got {sorted(recording)}"
    )

    cited = adrs_cited_in(SHIM.read_text(encoding="utf-8"))

    assert cited == recording, (
        f"sync_claude.py cites ADR-{sorted(cited)} "
        f"but the rename is recorded in ADR-{sorted(recording)}"
    )


def test_self_test_extractors_read_the_heading_and_the_citation() -> None:
    adr_body = """# ADR-032: Something

### `core/sync_claude.py` rename

`sync_claude.py` -> `sync_agent_md.py`.
"""
    assert _RENAME_HEADING.search(adr_body) is not None
    # A mention in prose is not the section heading, so it must not match.
    assert _RENAME_HEADING.search("see the `core/sync_claude.py` rename below") is None

    assert adrs_cited_in('"""Renamed in ADR-032. Superseded by ADR-041."""') == {
        "032",
        "041",
    }
