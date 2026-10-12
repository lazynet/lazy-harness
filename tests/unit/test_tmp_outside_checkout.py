"""The suite never writes inside a git checkout, whatever TMPDIR says.

An agent session exports `TMPDIR=<repo>/tmp`, so pytest's `tmp_path` landed
inside the repo: tests deriving a project key from `tmp_path` found the outer
repo instead of their own fixture, and `CLAUDE.md` fixtures left under
`tmp/pytest-of-*` made `lh repo instructions` fail on the checkout itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.tmp_outside_checkout import relocation_target

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)
    return path


def test_a_tempdir_inside_a_checkout_is_relocated_outside_it(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    inside = repo / "tmp"
    inside.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    assert relocation_target(inside, basetemp=None, candidates=[outside]) == outside


def test_a_candidate_that_is_itself_in_a_checkout_is_skipped(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    inside = repo / "tmp"
    inside.mkdir()
    other_repo_tmp = _git_repo(tmp_path / "other") / "tmp"
    other_repo_tmp.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    target = relocation_target(inside, basetemp=None, candidates=[other_repo_tmp, outside])

    assert target == outside


def test_a_tempdir_outside_any_checkout_is_left_alone(tmp_path: Path) -> None:
    outside = tmp_path / "plain"
    outside.mkdir()

    assert relocation_target(outside, basetemp=None, candidates=[tmp_path]) is None


def test_an_explicit_basetemp_wins(tmp_path: Path) -> None:
    inside = _git_repo(tmp_path / "repo") / "tmp"
    inside.mkdir()

    target = relocation_target(inside, basetemp="/somewhere/explicit", candidates=[tmp_path])

    assert target is None


def _run_child_pytest(repo: Path, *extra: str) -> Path:
    (repo / "test_where.py").write_text(
        "def test_where(tmp_path):\n    print('TMP_PATH=' + str(tmp_path.resolve()))\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["TMPDIR"] = str(repo / "tmp")
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-s",
            "-p",
            "tests.tmp_outside_checkout",
            "-p",
            "no:cacheprovider",
            *extra,
            "test_where.py",
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("TMP_PATH="))
    return Path(line.removeprefix("TMP_PATH="))


def test_a_real_pytest_run_with_tmpdir_in_a_checkout_writes_outside_it(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "throwaway").resolve()
    (repo / "tmp").mkdir()

    child_tmp_path = _run_child_pytest(repo)

    assert not child_tmp_path.is_relative_to(repo), child_tmp_path
    assert not list((repo / "tmp").iterdir())


def test_a_real_pytest_run_keeps_an_explicit_basetemp(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "throwaway").resolve()
    (repo / "tmp").mkdir()
    basetemp = repo / "tmp" / "explicit"

    child_tmp_path = _run_child_pytest(repo, f"--basetemp={basetemp}")

    assert child_tmp_path.is_relative_to(basetemp), child_tmp_path
