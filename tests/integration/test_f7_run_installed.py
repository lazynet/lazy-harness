"""`run-installed.sh` wraps `isolation-gate.sh` once and reports the result
under the three agent shapes the user actually runs: `lazy` (claude-code),
`flex` (claude-code), `lazy-codex` (codex).

`isolation-gate.sh` takes only a binary path (`isolation-gate.sh
[path-to-lh]`) and returns ONE combined PASS/FAIL for both its lanes in a
single execution — it has no notion of a real profile name. It always builds
two THROWAWAY profiles of its own, one per adapter, so a second or third
execution against the same binary would build byte-identical profiles and
exercise the identical two lanes again: no new signal, only more wall-clock.
`lazy` and `flex` both dispatch through the claude-code adapter and are
therefore the same lane as far as the gate can tell.

These tests stub `isolation-gate.sh` itself, both to keep the suite fast (a
real run costs ~17s even against a shell stub, per
`test_f7_gate_binary_resolution.py`) and to control PASS vs FAIL
deterministically without a real registry or hook run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
WRAPPER_SH = REPO_ROOT / "specs" / "gates" / "f7" / "run-installed.sh"

SHAPES = ("lazy", "flex", "lazy-codex")

_PASS_GATE = "#!/bin/sh\necho fake gate ran\nexit 0\n"
_FAIL_GATE = (
    "#!/bin/sh\n"
    "echo fake gate ran\n"
    "echo '  FAIL: codex full/agentenv pre-tool-use-security did not reach profile dir'\n"
    "exit 1\n"
)


def _stub_lh(tmp_path: Path) -> Path:
    lh = tmp_path / "lh"
    lh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    lh.chmod(0o755)
    return lh


def _stub_gate(tmp_path: Path, body: str) -> Path:
    gate = tmp_path / "isolation-gate.sh"
    gate.write_text(body, encoding="utf-8")
    gate.chmod(0o755)
    return gate


def _run(
    lh_bin: str, tmp_path: Path, gate: Path, out_dir: Path
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["F7_RUN_INSTALLED_GATE"] = str(gate)
    env["F7_RUN_INSTALLED_OUT_DIR"] = str(out_dir)
    args = ["bash", str(WRAPPER_SH)]
    if lh_bin:
        args.append(lh_bin)
    return subprocess.run(
        args, capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=60
    )


def test_a_relative_lh_path_is_refused_before_the_gate_runs(tmp_path: Path) -> None:
    _stub_lh(tmp_path)
    gate = _stub_gate(tmp_path, _PASS_GATE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run("./lh", tmp_path, gate, out_dir)

    assert result.returncode == 2
    assert not any(out_dir.iterdir()), "the gate ran despite a relative path"


def test_a_missing_lh_binary_is_refused(tmp_path: Path) -> None:
    gate = _stub_gate(tmp_path, _PASS_GATE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run(str(tmp_path / "nope"), tmp_path, gate, out_dir)

    assert result.returncode == 2
    assert not any(out_dir.iterdir())


def test_all_three_shapes_pass_and_get_their_own_output_file(tmp_path: Path) -> None:
    lh = _stub_lh(tmp_path)
    gate = _stub_gate(tmp_path, _PASS_GATE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run(str(lh), tmp_path, gate, out_dir)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    for shape in SHAPES:
        f = out_dir / f"f7-{shape}.txt"
        assert f.exists(), f"missing {f}"
        assert "fake gate ran" in f.read_text(encoding="utf-8")
        assert shape in result.stdout
    assert "PASS" in result.stdout


def test_a_failing_gate_fails_every_shape_and_still_writes_evidence(tmp_path: Path) -> None:
    """The fixture that must fail: a gate reporting a leak must not be reported PASS."""
    lh = _stub_lh(tmp_path)
    gate = _stub_gate(tmp_path, _FAIL_GATE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = _run(str(lh), tmp_path, gate, out_dir)

    assert result.returncode != 0
    assert "FAIL" in result.stdout
    for shape in SHAPES:
        f = out_dir / f"f7-{shape}.txt"
        assert f.exists(), (
            f"evidence for {shape} missing even though the runner must report failure"
        )
        assert "FAIL:" in f.read_text(encoding="utf-8")


def test_a_symlink_planted_at_a_shape_output_path_is_replaced_not_followed(
    tmp_path: Path,
) -> None:
    """A pre-planted symlink at `f7-<shape>.txt` must be atomically replaced,
    never written through — these are stable, predictable names in a
    directory that defaults to the shared, world-writable `/tmp`."""
    lh = _stub_lh(tmp_path)
    gate = _stub_gate(tmp_path, _PASS_GATE)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    target = tmp_path / "do-not-touch.txt"
    target.write_text("precious", encoding="utf-8")
    dest = out_dir / "f7-lazy.txt"
    dest.symlink_to(target)

    result = _run(str(lh), tmp_path, gate, out_dir)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert target.read_text(encoding="utf-8") == "precious", "the symlink target was overwritten"
    assert not dest.is_symlink(), "the symlink was written through instead of replaced"
    assert "fake gate ran" in dest.read_text(encoding="utf-8")


def test_the_script_is_syntactically_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(WRAPPER_SH)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not on PATH")
def test_shellcheck_is_clean() -> None:
    result = subprocess.run(
        ["shellcheck", "--severity=warning", str(WRAPPER_SH)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout
