"""The `/cleanup-worktree` merge check must never call an unmerged branch merged.

The check is prose an agent executes verbatim, so these tests extract the exact
snippet from the command file and run it under both shells the harness uses.
`zsh` does not word-split unquoted parameter expansions and `bash` splits them on
whitespace, so a file list interpolated into a pathspec behaves differently in
each -- and a pathspec matching nothing yields an empty diff, which reads as
"merged".
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

COMMAND_FILE = Path(__file__).resolve().parents[2] / ".claude" / "commands" / "cleanup-worktree.md"
MARKER = "# merge-check"
SHELLS = ("bash", "zsh")


def extract_merge_check() -> str:
    """Return the fenced bash block whose first line is the merge-check marker."""
    lines = COMMAND_FILE.read_text(encoding="utf-8").splitlines()
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if current is None:
            if line.strip() == "```bash":
                current = []
            continue
        if line.strip() == "```":
            blocks.append(current)
            current = None
            continue
        current.append(line)

    marked = [b for b in blocks if b and b[0].strip() == MARKER]
    assert len(marked) == 1, (
        f"expected exactly one ```bash block starting with {MARKER!r} in "
        f"{COMMAND_FILE}, found {len(marked)}"
    )
    return "\n".join(marked[0])


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    return repo


def commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for name, content in files.items():
        (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def publish_main(repo: Path) -> None:
    """Point refs/remotes/origin/main at local main, as a fetch would."""
    sha = git(repo, "rev-parse", "main").strip()
    git(repo, "update-ref", "refs/remotes/origin/main", sha)


def run_check(repo: Path, shell: str, branch: str = "feature") -> str:
    binary = shutil.which(shell)
    if binary is None:
        pytest.skip(f"{shell} not installed")
    result = subprocess.run(
        [binary, "-f", "-c", extract_merge_check()],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "BRANCH": branch, "HOME": str(repo)},
    )
    assert result.returncode == 0, f"snippet failed under {shell}: {result.stderr}"
    return result.stdout


def make_branch(repo: Path, files: dict[str, str]) -> None:
    git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, "feature work", files)
    git(repo, "checkout", "-q", "main")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path)
    commit(repo, "init", {"a.txt": "a\n", "b.txt": "b\n", "c.txt": "c\n"})
    publish_main(repo)
    return repo


@pytest.mark.parametrize("shell", SHELLS)
def test_multi_file_unmerged_branch_reports_unmerged(repo: Path, shell: str) -> None:
    make_branch(repo, {"a.txt": "a2\n", "b.txt": "b2\n", "c.txt": "c2\n"})

    assert "UNMERGED" in run_check(repo, shell)


@pytest.mark.parametrize("shell", SHELLS)
def test_single_file_unmerged_branch_reports_unmerged(repo: Path, shell: str) -> None:
    make_branch(repo, {"a.txt": "a2\n"})

    assert "UNMERGED" in run_check(repo, shell)


@pytest.mark.parametrize("shell", SHELLS)
def test_unmerged_branch_touching_a_path_with_a_space(repo: Path, shell: str) -> None:
    make_branch(repo, {"a.txt": "a2\n", "with space.txt": "s\n"})

    assert "UNMERGED" in run_check(repo, shell)


@pytest.mark.parametrize("shell", SHELLS)
def test_squash_merged_branch_reports_merged(repo: Path, shell: str) -> None:
    changed = {"a.txt": "a2\n", "b.txt": "b2\n", "c.txt": "c2\n"}
    make_branch(repo, changed)
    commit(repo, "squash of feature work", changed)
    publish_main(repo)

    assert "MERGED" in run_check(repo, shell)
    assert "UNMERGED" not in run_check(repo, shell)


@pytest.mark.parametrize("shell", SHELLS)
def test_squash_merged_branch_stays_merged_when_main_moves_on(repo: Path, shell: str) -> None:
    changed = {"a.txt": "a2\n", "b.txt": "b2\n", "c.txt": "c2\n"}
    make_branch(repo, changed)
    commit(repo, "squash of feature work", changed)
    commit(repo, "unrelated work", {"d.txt": "d\n"})
    publish_main(repo)

    assert "UNMERGED" not in run_check(repo, shell)


@pytest.mark.parametrize("shell", SHELLS)
def test_branch_with_no_changes_reports_merged(repo: Path, shell: str) -> None:
    git(repo, "branch", "feature", "main")

    assert "MERGED" in run_check(repo, shell)
