"""Tell a test-written fake from a real Claude Code install.

The suite's fakes are a few bytes of text, often shebang scripts and sometimes
named like a real version. A real install is a native executable of hundreds of
megabytes, and Claude Code can add one mid-run by auto-updating.
"""

from __future__ import annotations

import os
from pathlib import Path

_NATIVE_MAGIC = (
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit
    b"\xce\xfa\xed\xfe",  # Mach-O 32-bit, little-endian
    b"\xcf\xfa\xed\xfe",  # Mach-O 64-bit, little-endian
    b"\xca\xfe\xba\xbe",  # Mach-O universal
)
# Real builds weigh 200+ MB; a copied interpreter or helper binary is native
# too, but tiny by comparison.
_MIN_REAL_SIZE = 50 * 1024 * 1024


def looks_like_test_fake(entry: Path) -> bool:
    """True unless `entry` is a native executable the size of a real install.

    A symlink is a fake whatever it points at: the stat and the magic bytes
    follow it, and an installer writes regular files.
    """
    if os.path.islink(entry) or not entry.is_file():
        return True
    if entry.stat().st_size < _MIN_REAL_SIZE:
        return True
    with entry.open("rb") as fh:
        return fh.read(4) not in _NATIVE_MAGIC


def new_fakes(versions: Path, before: set[Path]) -> list[str]:
    """Names of the fakes in `versions` that were not there in `before`."""
    after = set(versions.iterdir()) if versions.is_dir() else set()
    return sorted(p.name for p in after - before if looks_like_test_fake(p))
