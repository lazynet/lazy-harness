"""Parse a version number out of a tool's `--version` output.

Three call sites probed a binary and took the last whitespace-separated token,
which holds only while every tool prints the version last. qmd prints a build
hash after it — `qmd 2.5.3 (5b90e281d4)` — so `lh doctor` reported the hash as
the installed version and the drift check compared a pin against it.

Deliberately not importing anything from the harness: `core/config.py` imports
the pins from the two wrapper modules, and those wrappers call this. A
dependency in the other direction would close the cycle.
"""

from __future__ import annotations

import re

# The tool name comes first and the decoration last, so the FIRST match wins.
# A leading `v` is decoration too: comparing `v1.16.1` against a bare pin
# reports drift between two equal versions.
_VERSION = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?(?:[-+.][0-9A-Za-z.-]+)?)")


def parse_version(output: str) -> str:
    """Return the version in `output`, or empty string when there is none.

    Empty rather than a fallback token: `lh doctor` renders any non-empty
    value as the installed version, so guessing is how a build hash gets
    printed as if it were a release.
    """
    match = _VERSION.search(output)
    return match.group(1) if match else ""
