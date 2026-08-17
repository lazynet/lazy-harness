"""Exception text must never reach rich as markup.

Two behavioural tests in `tests/integration/test_scheduler_cmd.py` pin the
symptom on the path where it was observed. This one pins the class: the defect
was spread across 38 interpolations in 9 files, so the next `console.print`
written in the obvious style reintroduces it silently — the message still
renders, only without the identifier it existed to name.
"""

from __future__ import annotations

import re
from pathlib import Path

# `{e}` and friends are the names this codebase binds exceptions to in
# `except ... as <name>` clauses.
_UNESCAPED = re.compile(r"console\.print\(f\"[^\"]*\{(e|exc|err|error)\}")

_SOURCE = Path(__file__).resolve().parents[2] / "src" / "lazy_harness"


def test_no_console_print_interpolates_unescaped_exception_text() -> None:
    offenders: list[str] = []
    for path in sorted(_SOURCE.rglob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if _UNESCAPED.search(line):
                offenders.append(f"{path.relative_to(_SOURCE)}:{number}: {line.strip()}")

    assert not offenders, (
        "rich parses `[...]` in an interpolated message as a markup tag and "
        "deletes it. Wrap the value in `escape(str(...))`:\n" + "\n".join(offenders)
    )


def test_the_guard_matches_the_shape_it_is_written_against() -> None:
    """A regex guard that matches nothing would pass forever."""
    assert _UNESCAPED.search('    console.print(f"[red]Error: {e}[/red]")')
    assert _UNESCAPED.search('    console.print(f"[red]Error:[/red] {e}")')
    assert not _UNESCAPED.search('    console.print(f"[red]Error: {escape(str(e))}[/red]")')
