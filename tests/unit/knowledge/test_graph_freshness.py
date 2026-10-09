"""The freshness rule: graph.json is fresh when it is at least as new as the last
commit that touched a file graphify indexes as code.

Runs against real git repositories; commit dates are frozen through
`GIT_COMMITTER_DATE` and the graph mtime through `os.utime`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from lazy_harness.knowledge import graph_freshness as gf

T0 = 1_700_000_000


def _git(root: Path, *args: str, ts: int = T0) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": f"@{ts} +0000",
        "GIT_COMMITTER_DATE": f"@{ts} +0000",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env)


def _commit(root: Path, rel: str, ts: int) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{ts}\n")
    _git(root, "add", rel, ts=ts)
    _git(root, "commit", "-qm", f"touch {rel}", ts=ts)


def _graph(root: Path, ts: int) -> Path:
    out = root / "graphify-out"
    out.mkdir(exist_ok=True)
    graph = out / "graph.json"
    graph.write_text(json.dumps({"nodes": [], "links": []}))
    os.utime(graph, (ts, ts))
    return graph


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    return root


def test_a_docs_only_commit_after_the_graph_leaves_it_fresh(repo: Path) -> None:
    _commit(repo, "src/app.py", T0)
    _graph(repo, T0 + 10)
    _commit(repo, "README.md", T0 + 100)

    assert gf.is_fresh(repo) is True


def test_a_code_commit_after_the_graph_makes_it_stale(repo: Path) -> None:
    _commit(repo, "src/app.py", T0)
    _graph(repo, T0 + 10)
    _commit(repo, "src/other.py", T0 + 100)

    assert gf.is_fresh(repo) is False


def test_a_graph_exactly_at_the_last_code_commit_is_fresh(repo: Path) -> None:
    _commit(repo, "app.py", T0)
    _graph(repo, T0)

    assert gf.is_fresh(repo) is True


def test_a_repo_with_no_code_commit_is_fresh_when_the_graph_exists(repo: Path) -> None:
    _commit(repo, "README.md", T0 + 100)
    _graph(repo, T0)

    assert gf.last_code_commit_ts(repo) is None
    assert gf.is_fresh(repo) is True


def test_a_missing_graph_is_not_fresh(repo: Path) -> None:
    _commit(repo, "app.py", T0)

    assert gf.is_fresh(repo) is False


def test_the_last_code_commit_time_skips_later_docs_commits(repo: Path) -> None:
    _commit(repo, "app.py", T0)
    _commit(repo, "docs/a.md", T0 + 50)

    assert gf.last_code_commit_ts(repo) == T0


@pytest.mark.parametrize(
    "rel", ["solver.F90", "deep/nested/dir/mod.ts", "infra/main.tf", "cfg.json"]
)
def test_uppercase_and_nested_code_paths_are_matched(repo: Path, rel: str) -> None:
    _commit(repo, rel, T0 + 7)

    assert gf.last_code_commit_ts(repo) == T0 + 7


def test_a_non_repo_directory_is_unknown(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    _graph(plain, T0)

    assert gf.last_code_commit_ts(plain) is None
    assert gf.is_fresh(plain) is None


def test_git_missing_is_unknown(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _commit(repo, "app.py", T0)
    _graph(repo, T0 - 10)

    def boom(*_a: object, **_k: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(gf.subprocess, "run", boom)

    assert gf.is_fresh(repo) is None


def _count_git_log(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []
    real = subprocess.run

    def spy(cmd: list[str], *a: object, **k: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        return real(cmd, *a, **k)  # type: ignore[call-overload,no-any-return]

    monkeypatch.setattr(gf.subprocess, "run", spy)
    return calls


def test_a_second_call_on_the_same_head_does_not_run_git_log(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _commit(repo, "app.py", T0)
    _graph(repo, T0 + 10)
    assert gf.is_fresh(repo) is True

    calls = _count_git_log(monkeypatch)
    assert gf.is_fresh(repo) is True

    assert [c for c in calls if "log" in c] == []
    assert len(calls) == 1  # rev-parse HEAD only


def test_a_new_head_invalidates_the_cache(repo: Path) -> None:
    _commit(repo, "app.py", T0)
    _graph(repo, T0 + 10)
    assert gf.is_fresh(repo) is True

    _commit(repo, "more.py", T0 + 100)

    assert gf.is_fresh(repo) is False


@pytest.mark.parametrize("garbage", ["{not json", "[]", "null", '{"head": 3, "ts": "x"}', ""])
def test_a_corrupted_cache_is_recomputed(repo: Path, garbage: str) -> None:
    _commit(repo, "app.py", T0)
    _graph(repo, T0 + 10)
    cache = repo / "graphify-out" / "cache" / "lh-freshness.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(garbage)

    assert gf.is_fresh(repo) is True
    assert gf.last_code_commit_ts(repo) == T0


def test_an_unwritable_cache_location_still_answers(repo: Path) -> None:
    _commit(repo, "app.py", T0)
    _graph(repo, T0 + 10)
    (repo / "graphify-out" / "cache").write_text("a file where the directory should be")

    assert gf.is_fresh(repo) is True


def test_the_cache_is_not_created_without_a_graph_directory(repo: Path) -> None:
    _commit(repo, "app.py", T0)

    gf.last_code_commit_ts(repo)

    assert not (repo / "graphify-out").exists()


def test_code_extensions_cover_the_common_languages() -> None:
    assert {".py", ".ts", ".go", ".rs", ".sh", ".json", ".F90"} <= gf.CODE_EXTENSIONS
    assert ".md" not in gf.CODE_EXTENSIONS


def test_a_cached_timestamp_of_the_wrong_type_is_recomputed(repo: Path) -> None:
    _commit(repo, "app.py", T0)
    _graph(repo, T0 + 10)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    cache = repo / "graphify-out" / "cache" / "lh-freshness.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"head": head, "ts": "soon"}))

    assert gf.last_code_commit_ts(repo) == T0


def test_a_repo_with_no_code_commit_is_also_served_from_the_cache(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _commit(repo, "README.md", T0)
    _graph(repo, T0)
    assert gf.is_fresh(repo) is True

    calls = _count_git_log(monkeypatch)
    assert gf.is_fresh(repo) is True

    assert [c for c in calls if "log" in c] == []
