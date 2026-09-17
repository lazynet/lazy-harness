"""`codex-acceptance.sh --dry-run` prints the run and spawns nothing.

The F9 gate is the one gate in `specs/gates/` that cannot be exercised here at
all: every phase it asserts on needs a real `[profiles.lazy-codex]`, a real `codex`
binary and a real `lh deploy` against the user's own Codex config dir, run from
a plain terminal. `--dry-run` exists so the *script* is still testable even
though the *gate* is not, and this file is the whole of that coverage.

**The property under test is an absence**, which is the trap. "No process was
spawned" passes just as well when the script is broken, when it exits on line 3,
or when `--dry-run` does nothing at all — so an absence asserted on its own
covers nothing. The two run tests are therefore a pair and are only meaningful
together:

    dry_run_spawns_nothing            --dry-run   -> witness file absent
    a_real_run_reaches_for_the_binary (no flag)   -> witness file present

The second is what makes the first load-bearing: it proves the shims are
reachable, executable and observed on this PATH, so the empty witness in the
first run is `--dry-run` suppressing execution rather than the harness failing
to look. Deleting the `--dry-run` guard from the script turns the first red;
deleting the shim wiring turns the second red.

The shims exit 97 rather than 0 for the same reason: a shim that succeeds lets a
broken script continue and report a phase it never ran.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SH = REPO_ROOT / "specs" / "gates" / "f9" / "codex-acceptance.sh"

PROFILE = "lazy-codex"

# The phase banners, in the order the run must print them. Typed here and
# grepped out of the script's output rather than read from it, so a phase
# silently dropped from the script fails this test instead of rewriting it.
PHASES = (
    "preflight",
    "phase-a-untrusted",
    "phase-b-trusted",
    "phase-c-reapproval",
    "summary",
)

_SHIM = """#!/bin/sh
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$F9_TEST_WITNESS"
exit 97
"""


def _shims(tmp_path: Path) -> tuple[Path, Path]:
    """A bin dir whose `lh`, `codex` and `gtimeout` all refuse loudly.

    `timeout` is shimmed too: it is the one preflight binary a macOS box may
    genuinely lack, and letting the real one through would make this fixture's
    behaviour depend on whether coreutils is installed.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("lh", "codex", "timeout", "gtimeout"):
        shim = bin_dir / name
        shim.write_text(_SHIM, encoding="utf-8")
        shim.chmod(0o755)
    return bin_dir, tmp_path / "witness"


def _fake_config(tmp_path: Path) -> Path:
    """An `LH_CONFIG_DIR` declaring one Codex profile and one Claude Code one.

    Two profiles, not one: the gate resolves its subject by name, and a config
    with a single profile cannot tell "read `$1`" apart from "took the only one
    there was".
    """
    lh_config = tmp_path / "lh"
    lh_config.mkdir()
    (lh_config / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        '[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "cc"\n\n'
        f'[profiles.cc]\nconfig_dir = "{tmp_path / "cfg-cc"}"\nroots = []\n\n'
        f'[profiles.{PROFILE}]\nconfig_dir = "{tmp_path / "cfg-codex"}"\nroots = []\n'
        'agent = "codex"\n',
        encoding="utf-8",
    )
    return lh_config


def _run_gate(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    bin_dir, witness = _shims(tmp_path)
    lh_config = _fake_config(tmp_path)

    env = dict(os.environ)
    # Prepended, not replaced: the script is bash and still needs a real
    # coreutils around it. Only the four shimmed names are shadowed.
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["LH_CONFIG_DIR"] = str(lh_config)
    env["LH_DATA_DIR"] = str(tmp_path / "data")
    env["LH_CACHE_DIR"] = str(tmp_path / "cache")
    env["F9_TEST_WITNESS"] = str(witness)

    return subprocess.run(
        ["bash", str(GATE_SH), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=120,
    )


def test_dry_run_prints_every_phase_in_order(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, "--dry-run", PROFILE)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    positions = []
    for phase in PHASES:
        index = result.stdout.find(phase)
        assert index >= 0, f"phase {phase!r} missing from the dry run:\n{result.stdout}"
        positions.append(index)

    assert positions == sorted(positions), (
        f"phases printed out of order: {list(zip(PHASES, positions, strict=True))}"
    )


def test_dry_run_substitutes_the_profile_into_the_commands_it_prints(tmp_path: Path) -> None:
    """A dry run that printed the placeholder would document nothing."""
    result = _run_gate(tmp_path, "--dry-run", PROFILE)

    assert f"--profile {PROFILE}" in result.stdout
    assert "<profile>" not in result.stdout

    # An unexpanded `$(...)` in a printed command is the same defect wearing a
    # different placeholder: the reader is handed a command they have to finish.
    # Only the `$ `-prefixed command lines are checked — the prose above them
    # cites shell and Python expressions on purpose.
    unexpanded = [
        line
        for line in result.stdout.splitlines()
        if line.lstrip().startswith("$ ") and "$(" in line
    ]
    assert not unexpanded, f"dry run printed unexpanded substitutions: {unexpanded}"


def test_dry_run_spawns_no_lh_and_no_codex(tmp_path: Path) -> None:
    """The half of the pair that is an absence. Read its partner below."""
    result = _run_gate(tmp_path, "--dry-run", PROFILE)
    witness = tmp_path / "witness"

    assert result.returncode == 0, result.stderr
    assert not witness.exists(), "--dry-run invoked a real binary: " + witness.read_text(
        encoding="utf-8"
    )


def test_a_real_run_reaches_for_the_binary_the_dry_run_left_alone(tmp_path: Path) -> None:
    """The half that proves the shims are reachable and observed.

    Without `--dry-run` the preflight runs `lh --version` for real, hits the
    shim's exit 97 and refuses with the harness-error code. Exit 2, not 1: a
    missing or broken `lh` means the gate could not be run, never that the
    system under test failed it.
    """
    result = _run_gate(tmp_path, PROFILE)
    witness = tmp_path / "witness"

    assert witness.exists(), (
        "no shim was invoked without --dry-run, so the absence asserted by "
        f"test_dry_run_spawns_no_lh_and_no_codex proves nothing:\n{result.stdout}"
    )
    assert "lh" in witness.read_text(encoding="utf-8")
    assert result.returncode == 2, f"expected harness error, got {result.returncode}"


def test_the_gate_refuses_without_a_profile(tmp_path: Path) -> None:
    """`$1` is required; defaulting it would run the phases against a guess."""
    result = _run_gate(tmp_path, "--dry-run")

    assert result.returncode == 2
    assert "profile" in (result.stdout + result.stderr).lower()


def test_a_blocked_assertion_cannot_exit_zero() -> None:
    """B5 blocked by ADR-053 must not be filed as a pass.

    The verdict logic only runs in a real gate run, so this reads the script's
    own summary block rather than driving it: the three things that make BLOCKED
    a distinct outcome are that it has its own tally, that it is checked before
    either PASS branch, and that it exits non-zero. A `blocked()` that fell
    through to `PASS WITH GAPS` would exit 0, and a caller reading only the exit
    code would record the iteration's criterion as met on a run that never
    reached it.
    """
    script = GATE_SH.read_text(encoding="utf-8")

    assert "blocked()" in script, "no blocked() helper"
    assert "exit 3" in script, "BLOCKED does not have its own exit code"

    summary = script[script.index("--- summary ---") :]
    blocked_at = summary.index('if [ "$BLOCKED" -gt 0 ]')
    pass_at = summary.index('echo "PASS — ')
    assert blocked_at < pass_at, "the BLOCKED branch must be checked before PASS"


def test_the_script_is_syntactically_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(GATE_SH)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not on PATH")
def test_shellcheck_is_clean() -> None:
    result = subprocess.run(
        ["shellcheck", "--severity=warning", str(GATE_SH)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout
