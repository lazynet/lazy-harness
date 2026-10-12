"""The versions-dir guard flags a test's fake, never a real Claude Code install.

A Claude Code auto-update during a run adds a real entry to
`~/.local/share/claude/versions/`, and the guard failed the whole suite on it.
Every fake the suite writes is a few bytes of text, often a shebang script and
sometimes named like a real version; a real install is a native executable of
hundreds of megabytes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.claude_versions_guard import looks_like_test_fake, new_fakes

MACHO_64 = b"\xcf\xfa\xed\xfe"
ELF = b"\x7fELF"
REAL_SIZE = 240 * 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[2]


def _native(path: Path, magic: bytes, size: int) -> Path:
    with path.open("wb") as fh:
        fh.write(magic)
        fh.truncate(size)
    return path


@pytest.mark.parametrize("name", ["0.0.1-fake", "2.1.297"])
@pytest.mark.parametrize("body", ["#!/bin/sh\nexit 0\n", "#!/usr/bin/python3\npass\n", "new\n"])
def test_a_text_fake_is_flagged_whatever_its_name(tmp_path: Path, name: str, body: str) -> None:
    fake = tmp_path / name
    fake.write_text(body)
    fake.chmod(0o755)
    assert looks_like_test_fake(fake)


@pytest.mark.parametrize("magic", [MACHO_64, ELF])
def test_a_real_install_is_ignored(tmp_path: Path, magic: bytes) -> None:
    assert not looks_like_test_fake(_native(tmp_path / "2.1.297", magic, REAL_SIZE))


def test_a_script_padded_to_a_real_size_is_flagged(tmp_path: Path) -> None:
    assert looks_like_test_fake(_native(tmp_path / "2.1.297", b"#!/bin/sh\n", REAL_SIZE))


def test_a_small_native_executable_is_flagged(tmp_path: Path) -> None:
    # A copied interpreter or helper binary: native, but nowhere near a real install.
    assert looks_like_test_fake(_native(tmp_path / "2.1.297", MACHO_64, 64 * 1024))


def test_a_symlink_to_a_real_install_is_flagged(tmp_path: Path) -> None:
    real = _native(tmp_path / "real", MACHO_64, REAL_SIZE)
    link = tmp_path / "2.1.297"
    link.symlink_to(real)
    assert looks_like_test_fake(link)


def test_a_directory_is_flagged(tmp_path: Path) -> None:
    entry = tmp_path / "2.1.297"
    entry.mkdir()
    assert looks_like_test_fake(entry)


def test_only_new_fakes_are_reported(tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "2.1.200").write_text("#!/bin/sh\n")
    before = set(versions.iterdir())
    _native(versions / "2.1.297", MACHO_64, REAL_SIZE)
    (versions / "2.1.298").write_text("#!/bin/sh\nexit 0\n")

    assert new_fakes(versions, before) == ["2.1.298"]


def test_a_missing_versions_dir_reports_nothing(tmp_path: Path) -> None:
    assert new_fakes(tmp_path / "absent", set()) == []


_WRITES_INTO_VERSIONS = """
import os
from pathlib import Path

def test_writes():
    entry = Path(os.environ["PROBE_VERSIONS"]) / "2.1.299"
    if os.environ["PROBE_KIND"] == "fake":
        entry.write_text("#!/bin/sh\\nexit 0\\n")
    else:
        with entry.open("wb") as fh:
            fh.write(MAGIC)
            fh.truncate(SIZE)
""".replace("MAGIC", repr(MACHO_64)).replace("SIZE", str(REAL_SIZE))


@pytest.mark.parametrize(("kind", "fails"), [("fake", True), ("real", False)])
def test_the_session_guard_fails_on_a_fake_and_not_on_an_auto_update(
    tmp_path: Path, kind: str, fails: bool
) -> None:
    # A child session whose own HOME stands in for the developer's: the guard
    # snapshots it at import, and a test writes into it past `_isolate_home_dir`,
    # which redirects HOME inside the test.
    home = tmp_path / "home"
    versions = home / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True)
    probe = tmp_path / "probe" / "test_writes.py"
    probe.parent.mkdir()
    probe.write_text(_WRITES_INTO_VERSIONS)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        + ["-p", "tests.conftest", str(probe)],
        cwd=REPO_ROOT,
        env={**os.environ, "HOME": str(home), "PROBE_VERSIONS": str(versions), "PROBE_KIND": kind},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (proc.returncode != 0) is fails, proc.stdout[-2000:]
    assert ("isolated HOME: ['2.1.299']" in proc.stdout) is fails
