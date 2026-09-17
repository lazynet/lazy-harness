"""The shell the repo ships must parse under bash 3.2, which is macOS `/bin/bash`.

A heredoc opened inside a command substitution is the trap, and it is invisible
on a development machine. Bash 3.2 scans the heredoc body looking for the `)`
that closes the substitution, and it honours quoting while it scans — so one
apostrophe in a comment inside that body leaves an unmatched `'`, and the whole
script becomes unparseable. Bash 4+ does not do this, so `bash -n` against a
homebrew bash 5 says the file is fine.

That is exactly how it landed: a Python comment reading "probe 4's hand-escaped
envelope", inside a `DENY_RULES="$(... <<'PY'` block, parsed clean locally and
took every macOS job down with `syntax error: unexpected end of file` pointing
at the last line of the file — a thousand lines from the cause.

**Two tests, and the second is the one that runs everywhere.** The first parses
with bash 3.2 when the machine has one and skips otherwise, so it is worthless
as the only guard: CI's Linux jobs would never execute it. The second is the
rule itself, checked by reading the files, and it fails on Linux and macOS
alike.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
GATES = REPO_ROOT / "specs" / "gates"

# A heredoc opened on a line that also opens a command substitution. The
# narrowest form that catches the real case without flagging every heredoc in
# the repo: outside `$(...)` the body is not rescanned for a closing paren and
# an apostrophe in it is harmless.
_SUBSTITUTION_HEREDOC = re.compile(r"\$\(.*<<-?'?(?P<tag>[A-Za-z_][A-Za-z0-9_]*)'?")


def _shell_files() -> list[Path]:
    files = sorted(GATES.rglob("*.sh"))
    assert files, f"no shell files under {GATES} — the guard would pass vacuously"
    return files


def _risky_heredoc_bodies(text: str) -> list[tuple[str, int, str]]:
    """Every `(tag, line number, line)` inside a heredoc opened within `$(...)`."""
    found: list[tuple[str, int, str]] = []
    tag: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if tag is None:
            match = _SUBSTITUTION_HEREDOC.search(line)
            if match:
                tag = match.group("tag")
            continue
        if line.strip() == tag:
            tag = None
            continue
        found.append((tag, number, line))
    return found


def test_the_detector_finds_a_body_it_should_flag() -> None:
    """The guard below is an absence, so its detector needs its own positive.

    Without this, deleting the regex's `\\$\\(` would make every file pass and
    the rule would be enforced on nothing.
    """
    sample = "X=\"$(python3 - <<'PY'\n# probe 4's envelope\nPY\n)\"\n"

    assert [line for _, _, line in _risky_heredoc_bodies(sample)] == ["# probe 4's envelope"]


def test_the_detector_ignores_a_heredoc_outside_a_substitution() -> None:
    """Outside `$(...)` the body is never rescanned, so flagging it would be
    noise that gets the rule switched off."""
    sample = "python3 - <<'PY'\n# probe 4's envelope\nPY\n"

    assert _risky_heredoc_bodies(sample) == []


@pytest.mark.parametrize("path", _shell_files(), ids=lambda p: p.name)
def test_no_apostrophe_inside_a_heredoc_opened_in_a_substitution(path: Path) -> None:
    """The rule, checked on every platform because bash 3.2 is on almost none."""
    offenders = [
        (number, line)
        for _, number, line in _risky_heredoc_bodies(path.read_text(encoding="utf-8"))
        if "'" in line
    ]

    assert offenders == [], (
        f"{path.name} has an apostrophe inside a heredoc opened within $(...); "
        f"bash 3.2 will not parse the file: {offenders}"
    )


@pytest.mark.skipif(
    not Path("/bin/bash").exists(), reason="no /bin/bash to check the old parser with"
)
@pytest.mark.parametrize("path", _shell_files(), ids=lambda p: p.name)
def test_the_system_bash_parses_every_gate_script(path: Path) -> None:
    """Real, and deliberately not the only guard: on Linux `/bin/bash` is 5.x
    and this proves nothing about 3.2. It is the macOS job that makes it bite."""
    assert shutil.which("bash"), "no bash at all"
    result = subprocess.run(
        ["/bin/bash", "-n", str(path)], capture_output=True, text=True, timeout=60
    )

    assert result.returncode == 0, result.stderr
