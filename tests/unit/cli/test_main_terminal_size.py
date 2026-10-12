"""`lh` prints its output when the shell exports `COLUMNS=0`.

Agent shells export `COLUMNS=0`. Rich reads any all-digit `COLUMNS` as an
explicit width, so a zero skips its own fallback to 80 and every `Console()`
renders nothing: `lh doctor` exited with no output at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli, unusable_terminal_size_vars

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("value", ["0", "00"])
def test_a_zero_terminal_size_is_unusable(value: str) -> None:
    assert unusable_terminal_size_vars({"COLUMNS": value, "LINES": value}) == [
        "COLUMNS",
        "LINES",
    ]


@pytest.mark.parametrize("value", ["80", "300", "", "wide"])
def test_a_size_rich_handles_itself_is_left_alone(value: str) -> None:
    assert unusable_terminal_size_vars({"COLUMNS": value, "LINES": value}) == []


def test_lh_prints_its_output_under_columns_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n'
        '[agent]\ntype = "claude-code"\n'
        '[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "~/.claude-p1"\n'
        '[knowledge]\nroot = ""\n'
    )
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.shutil.which", lambda _name: None)

    result = CliRunner().invoke(cli, ["doctor"], env={"COLUMNS": "0", "LINES": "0"})

    assert "ruff not found" in result.output.lower()


def test_the_suite_survives_columns_zero_when_a_subcommand_is_invoked_directly() -> None:
    # Most tests invoke a subcommand rather than `cli`, so the group never
    # runs: only the suite's own fixture keeps their consoles from going blank.
    env = {**os.environ, "COLUMNS": "0", "LINES": "0"}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/unit/cli/test_doctor_cmd.py::test_doctor_warns_when_ruff_missing",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:]
