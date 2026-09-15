"""`/tdd-check` and the `CLAUDE.md` rule that mandates it agree on what it runs.

Two halves of one contract living in different files. `CLAUDE.md` names the
gate and asserts a count; `.claude/commands/tdd-check.md` is the gate. A check
added to the command without updating the count leaves the always-loaded
governance surface understating the gate, which is the half agents read.

The count is derived from the command's own numbered headings rather than
written down twice, so adding a fifth check fails this test until the prose
follows — the same shape as the glob-completeness rule in `CLAUDE.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TDD_CHECK = REPO_ROOT / ".claude/commands/tdd-check.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

_CHECK_HEADING = re.compile(r"^## (?P<n>\d+)\. (?P<title>.+)$", re.MULTILINE)

# Only the counts the rule could plausibly carry; an unmapped word should read
# as a parse failure rather than silently scoring zero.
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

_STATED_COUNT = re.compile(
    r"`/tdd-check` passes before every commit\*\*, all (?P<word>\w+) checks",
)


def _gate_checks() -> list[str]:
    """The numbered checks `/tdd-check` declares, in order."""
    return [m.group("title") for m in _CHECK_HEADING.finditer(TDD_CHECK.read_text())]


def test_the_gate_headings_are_actually_found() -> None:
    """Guards the parser: a regex that matches nothing would make every
    assertion below vacuously true."""
    checks = _gate_checks()
    assert len(checks) >= 3, checks


def test_the_gate_runs_the_formatter() -> None:
    """`ruff check` and `ruff format` are disjoint. Lint rules do not reformat,
    so a repo running only the former drifts until a reformat lands as an
    unreviewable 44-file diff on top of somebody's logic change.
    """
    body = TDD_CHECK.read_text()
    assert "ruff format --check" in body
    assert any("format" in title.lower() for title in _gate_checks()), _gate_checks()


def test_claude_md_states_the_number_of_checks_the_gate_actually_runs() -> None:
    match = _STATED_COUNT.search(CLAUDE_MD.read_text())
    assert match is not None, "the /tdd-check non-negotiable no longer states a count"
    stated = _NUMBER_WORDS.get(match.group("word"))
    assert stated is not None, f"unmapped count word: {match.group('word')!r}"
    assert stated == len(_gate_checks()), (
        f"CLAUDE.md says {match.group('word')} checks, "
        f"tdd-check.md declares {len(_gate_checks())}: {_gate_checks()}"
    )
