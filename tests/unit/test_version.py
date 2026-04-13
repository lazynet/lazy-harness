"""Version coherence guardrails.

The package version lives in two places — `pyproject.toml` (what uv and
PyPI consume) and `src/lazy_harness/__init__.py` (what Python code and
`lh --version` consume). release-please is responsible for bumping both
in lockstep; this test guards against accidental drift.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from lazy_harness import __version__

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return data["project"]["version"]


def test_version_is_040() -> None:
    assert __version__ == "0.4.0"


def test_pyproject_and_dunder_version_agree() -> None:
    assert _pyproject_version() == __version__
