"""`resolve_gate_python` follows the installed `lh` symlink to its interpreter.

`uv tool install` publishes `lh` into `~/.local/bin` as a symlink whose target
is `~/.local/share/uv/tools/lazy-harness/bin/lh`; the venv's `python`/`python3`
lives beside the *target*, not beside the symlink. The gate's preflight used
to look beside the symlink itself
(`specs/gates/f9/codex-acceptance.sh:322-325` before this fix), so a real run
against an installed `lh` refused in preflight for the wrong reason (measured
with lh 0.71.0 installed, 2026-09-17).

The function is extracted from the script and evaluated on its own rather than
sourcing the whole script: a `--dry-run` invocation of the script hits
`exit 0` at its very end, so a `source ...; resolve_gate_python ...` one-liner
never reaches the second statement.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SH = REPO_ROOT / "specs" / "gates" / "f9" / "codex-acceptance.sh"

_FAKE_PYTHON = """#!/bin/sh
case "$*" in
  *"import lazy_harness"*) exit 0 ;;
  *) exit 1 ;;
esac
"""

_FAKE_LH = "#!/bin/sh\nexit 0\n"


def _function_source() -> str:
    result = subprocess.run(
        ["awk", "/^resolve_gate_python\\(\\) \\{/,/^}/", str(GATE_SH)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout, "resolve_gate_python() not found in codex-acceptance.sh"
    return result.stdout


def _resolve(*args: str) -> subprocess.CompletedProcess[str]:
    quoted = " ".join(f'"{a}"' for a in args)
    script = f"{_function_source()}\nresolve_gate_python {quoted}\n"
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)


def test_resolve_gate_python_follows_the_lh_symlink_to_the_venv_interpreter(
    tmp_path: Path,
) -> None:
    """`LH_BIN` is a symlink; the interpreter lives beside its target, named `python`."""
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").write_text(_FAKE_PYTHON, encoding="utf-8")
    (venv_bin / "python").chmod(0o755)
    (venv_bin / "lh").write_text(_FAKE_LH, encoding="utf-8")
    (venv_bin / "lh").chmod(0o755)

    local_bin = tmp_path / "local-bin"
    local_bin.mkdir()
    symlinked_lh = local_bin / "lh"
    symlinked_lh.symlink_to(venv_bin / "lh")

    result = _resolve(str(symlinked_lh))

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.stdout.strip() == str(venv_bin / "python")


def test_resolve_gate_python_refuses_and_names_the_searched_dir_when_none_imports(
    tmp_path: Path,
) -> None:
    """No importing interpreter beside a bare (non-symlinked) `lh`: refuse, name the dir."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    bare_lh = bin_dir / "lh"
    bare_lh.write_text(_FAKE_LH, encoding="utf-8")
    bare_lh.chmod(0o755)

    result = _resolve(str(bare_lh))

    assert result.returncode != 0
    assert "lazy_harness" in result.stderr
    assert str(bin_dir) in result.stderr, f"refusal did not name the searched dir:\n{result.stderr}"
