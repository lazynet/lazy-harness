"""Every script under `specs/gates/` must pass `shellcheck --severity=warning`.

`shellcheck-py` is a declared dev dependency (see `pyproject.toml`), so the
binary is expected on `PATH` inside the project's venv. No `skipif` guard: a
missing binary is a real failure, not a reason to skip.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SCRIPTS = sorted(REPO_ROOT.glob("specs/gates/**/*.sh"))

# Strict xfail: a later fix must flip these red until the marker is removed.
# Tracked in specs/backlog.md §Open.
XFAIL_REASONS = {}


def test_glob_is_not_empty() -> None:
    assert GATE_SCRIPTS


def _param(path: Path) -> pytest.ParameterSet:
    rel = str(path.relative_to(REPO_ROOT / "specs" / "gates"))
    reason = XFAIL_REASONS.get(rel)
    marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
    return pytest.param(path, id=str(path.relative_to(REPO_ROOT)), marks=marks)


@pytest.mark.parametrize("script", [_param(p) for p in GATE_SCRIPTS])
def test_gate_script_shellcheck_clean(script: Path) -> None:
    result = subprocess.run(
        ["shellcheck", "--severity=warning", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout
