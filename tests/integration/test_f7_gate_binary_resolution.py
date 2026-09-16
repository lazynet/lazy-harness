"""The F7 gate must hand its children a binary they can actually exec.

`isolation-gate.sh` validates its binary argument with `command -v` against the
**parent's** PATH, then invokes every hook with `env -i PATH=/usr/bin:/bin`. A
bare name or a relative path satisfies the parent check and is unreachable for
the child, and `invoke()` sends both streams to /dev/null and returns 0
unconditionally — so all 44 assertions fail with "no entry written anywhere the
gate watches" and the run reads as a production regression. Measured: it
fabricated exactly that false finding twice.

Running the whole gate to prove this costs ~17s even against a shell stub, which
is 20x the slowest test in this suite, so these tests cover the **resolution
alone** — the four shapes the argument can take, each measured by the script's
own exit code and diagnostic. The end-to-end proof (a stub `lh` counting its
invocations: 0 before the fix, 44 after) is recorded in the PR and the backlog
rather than run here.

The pair that carries the load is `relative` and `bare`: nothing non-absolute may
get through, and a bare name must still be accepted. Together they say the
accepted bare name was absolutised, because an absolute answer is the only way
past the guard.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SH = REPO_ROOT / "specs" / "gates" / "f7" / "isolation-gate.sh"


def _stub_binary(tmp_path: Path) -> Path:
    """An executable standing in for `lh`, reachable only via tmp_path."""
    stub = tmp_path / "lh"
    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


def _run_gate(argument: str, tmp_path: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the real gate, bounded to its binary preflight.

    `F7_GATE_ROOT` points at a file, so the script exits 2 a few lines after the
    binary block. Reaching *that* diagnostic is how a test observes that the
    argument was accepted; the run costs milliseconds and never reaches the
    registry read or a single hook invocation.
    """
    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    env["F7_GATE_ROOT"] = str(not_a_dir)

    return subprocess.run(
        ["bash", str(GATE_SH), argument],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=60,
    )


def test_a_relative_binary_path_is_refused_before_the_gate_runs(tmp_path: Path) -> None:
    """The child `cd`s elsewhere, so a relative path is unreachable for it."""
    _stub_binary(tmp_path)

    result = _run_gate("./lh", tmp_path, cwd=tmp_path)

    assert result.returncode == 2
    assert "./lh" in result.stderr
    # The ROOT diagnostic means the argument was accepted and the run moved on.
    assert "F7_GATE_ROOT" not in result.stderr, (
        "a relative binary path reached the gate body; the child would get a path "
        f"it cannot resolve. stderr: {result.stderr!r}"
    )


def test_a_bare_name_on_the_path_is_still_accepted(tmp_path: Path) -> None:
    """Absolutising must not reject the ordinary invocation.

    Paired with the relative-path test this is what says the bare name was
    resolved: after the fix an absolute answer is the only way past the guard.
    """
    _stub_binary(tmp_path)

    result = _run_gate("lh", tmp_path, cwd=REPO_ROOT)

    assert result.returncode == 2
    assert "F7_GATE_ROOT" in result.stderr, (
        f"a bare name on PATH was rejected by the binary preflight: {result.stderr!r}"
    )


def test_an_absolute_binary_path_is_accepted(tmp_path: Path) -> None:
    """The shape the gate's own documented invocation uses."""
    stub = _stub_binary(tmp_path)

    result = _run_gate(str(stub), tmp_path, cwd=REPO_ROOT)

    assert result.returncode == 2
    assert "F7_GATE_ROOT" in result.stderr, (
        f"an absolute binary path was rejected by the binary preflight: {result.stderr!r}"
    )


def test_a_name_that_resolves_to_nothing_still_exits_two(tmp_path: Path) -> None:
    """Pins the half that already worked, so the fix cannot quietly drop it."""
    result = _run_gate("definitely-not-on-any-path-xyz", tmp_path, cwd=REPO_ROOT)

    assert result.returncode == 2
    assert "definitely-not-on-any-path-xyz" in result.stderr
    assert "F7_GATE_ROOT" not in result.stderr
