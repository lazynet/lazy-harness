"""Tests for `graph_repos.collect_graph_health` — what the harness could not fix.

Real `git` against temporary repos with the machine's global git config swapped
for a throwaway one, as in `test_graph_repos.py`: `core.hooksPath` is global on
the developer's machine and would otherwise decide every hooks assertion.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from lazy_harness.core.config import Config
from lazy_harness.knowledge import graph_freshness
from lazy_harness.knowledge import graph_repos as gr


@pytest.fixture(autouse=True)
def isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    cfg = tmp_path / "global.gitconfig"
    cfg.write_text("[user]\n\tname = t\n\temail = t@example.com\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    return cfg


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "app.py").write_text("x = 1\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path.resolve()


def _install_hooks(repo: Path, hooks: Path | None = None) -> None:
    hooks = hooks or repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "post-commit").write_text(f"#!/bin/sh\n{gr._POST_COMMIT_MARK}\n")
    (hooks / "post-checkout").write_text(f"#!/bin/sh\n{gr._POST_CHECKOUT_MARK}\n")
    (hooks / "post-merge").write_text(f"#!/bin/sh\n{gr._POST_MERGE_BEGIN}\n{gr._POST_MERGE_END}\n")


def _graph(repo: Path, source_files: list[str] | None = None) -> Path:
    out = repo / "graphify-out"
    out.mkdir(exist_ok=True)
    nodes = [
        {"id": f"n{i}", "label": f"n{i}", "source_file": src}
        for i, src in enumerate(source_files or ["app.py"])
    ]
    graph = out / "graph.json"
    graph.write_text(json.dumps({"directed": False, "nodes": nodes, "links": []}, indent=2))
    return graph


def _names(checks: list[gr.HealthCheck]) -> list[str]:
    return [c.name for c in checks]


# --------------------------------------------------------------------- hooks


def test_hooks_present_in_the_repo_hooks_dir_raise_no_problem(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    _install_hooks(repo)

    assert gr.check_hooks(repo) == []


def test_a_missing_hook_is_an_error_naming_the_hook(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    _install_hooks(repo)
    (repo / ".git" / "hooks" / "post-merge").unlink()

    problems = gr.check_hooks(repo)

    assert [(p.name, p.status) for p in problems] == [("hooks", "error")]
    assert "post-merge" in problems[0].detail
    assert "missing" in problems[0].detail


def test_a_hook_file_without_the_graphify_marker_counts_as_missing(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    _install_hooks(repo)
    (repo / ".git" / "hooks" / "post-checkout").write_text("#!/bin/sh\nexit 0\n")

    problems = gr.check_hooks(repo)

    assert len(problems) == 1
    assert "post-checkout" in problems[0].detail


def test_a_hook_not_forwarded_by_core_hookspath_is_an_error(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    _install_hooks(repo)
    shared = tmp_path / "shared-hooks"
    shared.mkdir()
    (shared / "post-commit").write_text("#!/bin/sh\n")
    _git(repo, "config", "core.hooksPath", str(shared))

    problems = gr.check_hooks(repo)

    details = [p.detail for p in problems]
    assert f"post-checkout not forwarded by core.hooksPath ({shared})" in details
    assert f"post-merge not forwarded by core.hooksPath ({shared})" in details
    assert not any("post-commit" in d for d in details)
    assert all(p.status == "error" for p in problems)


def test_hooks_forwarded_by_core_hookspath_raise_no_problem(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    _install_hooks(repo)
    shared = tmp_path / "shared-hooks"
    shared.mkdir()
    for name in ("post-commit", "post-checkout", "post-merge"):
        (shared / name).symlink_to(repo / ".git" / "hooks" / name)
    _git(repo, "config", "core.hooksPath", str(shared))

    assert gr.check_hooks(repo) == []


def test_a_dangling_forwarding_symlink_is_not_forwarded(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    _install_hooks(repo)
    shared = tmp_path / "shared-hooks"
    shared.mkdir()
    for name in ("post-commit", "post-checkout"):
        (shared / name).symlink_to(repo / ".git" / "hooks" / name)
    (shared / "post-merge").symlink_to(tmp_path / "gone")
    _git(repo, "config", "core.hooksPath", str(shared))

    problems = gr.check_hooks(repo)

    assert [p.detail for p in problems] == [
        f"post-merge not forwarded by core.hooksPath ({shared})"
    ]


def test_a_relative_hookspath_resolves_against_the_repo_root(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    _install_hooks(repo)
    (repo / "githooks").mkdir()
    for name in ("post-commit", "post-checkout", "post-merge"):
        (repo / "githooks" / name).write_text("#!/bin/sh\n")
    _git(repo, "config", "core.hooksPath", "githooks")

    assert gr.check_hooks(repo) == []


def test_hooks_are_read_from_the_common_dir_inside_a_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    _install_hooks(repo)
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))

    assert gr.check_hooks(wt) == []


# ----------------------------------------------------------------- freshness


def test_a_fresh_graph_raises_no_freshness_problem(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    _graph(repo)

    assert gr.check_freshness(repo) == []


def test_a_graph_older_than_the_last_code_commit_is_stale_with_the_gap(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    graph = _graph(repo)
    ts = graph_freshness.last_code_commit_ts(repo)
    assert ts is not None
    old = ts - 3 * 86400 - 3600
    os.utime(graph, (old, old))

    problems = gr.check_freshness(repo)

    assert [(p.name, p.status) for p in problems] == [("freshness", "warning")]
    assert "stale" in problems[0].detail
    assert "3d" in problems[0].detail


def test_a_repo_with_no_graph_is_reported_as_having_none(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")

    problems = gr.check_freshness(repo)

    assert [(p.name, p.status) for p in problems] == [("freshness", "warning")]
    assert "no graph" in problems[0].detail


def test_a_docs_only_commit_after_the_graph_is_not_stale(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    graph = _graph(repo)
    ts = graph_freshness.last_code_commit_ts(repo)
    assert ts is not None
    os.utime(graph, (ts + 10, ts + 10))
    (repo / "NOTES.md").write_text("n\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "docs")

    assert gr.check_freshness(repo) == []


# ----------------------------------------------------------- last update log


def _log(path: Path, *lines: str) -> Path:
    path.write_text("".join(f"[2026-10-09 09:18:10] {line}\n" for line in lines))
    return path


def test_a_successful_last_update_raises_no_problem(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    log = _log(tmp_path / "u.log", f"updated: {repo}")

    assert gr.check_last_update(repo, log) == []


def test_a_failed_last_update_is_a_warning_carrying_the_line(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    log = _log(tmp_path / "u.log", f"failed: {repo}: graphify timed out after 600s")

    problems = gr.check_last_update(repo, log)

    assert [(p.name, p.status) for p in problems] == [("last update", "warning")]
    assert "graphify timed out after 600s" in problems[0].detail
    assert "2026-10-09 09:18:10" in problems[0].detail


def test_only_the_last_result_for_the_repo_counts(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    other = _repo(tmp_path / "other")
    log = _log(
        tmp_path / "u.log",
        f"failed: {repo}: boom",
        f"updated: {repo}",
        f"failed: {other}: elsewhere",
    )

    assert gr.check_last_update(repo, log) == []


def test_repair_and_index_lines_are_not_results(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    log = _log(
        tmp_path / "u.log",
        f"updated: {repo}",
        f"repair: {repo}: post-merge: failed: disk full",
        f"index failed: {repo}: nope",
    )

    assert gr.check_last_update(repo, log) == []


def test_a_repo_whose_path_is_a_prefix_of_another_is_not_confused(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    longer = Path(f"{repo}-two")
    log = _log(tmp_path / "u.log", f"updated: {repo}", f"failed: {longer}: boom")

    assert gr.check_last_update(repo, log) == []


def test_a_skipped_repo_is_a_warning(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    log = _log(tmp_path / "u.log", f"skipped: {repo} (missing)")

    problems = gr.check_last_update(repo, log)

    assert [p.status for p in problems] == ["warning"]


def test_a_missing_or_unreadable_log_raises_no_problem(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")

    assert gr.check_last_update(repo, tmp_path / "absent.log") == []
    assert gr.check_last_update(repo, tmp_path) == []


# ------------------------------------------------------------- ignored paths


def test_a_graph_with_no_ignored_sources_raises_no_problem(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    _graph(repo, ["app.py", "pkg/a.py", "pkg/b.py"])

    assert gr.check_ignored_in_graph(repo) == []


def test_nodes_under_an_ignored_directory_are_a_warning_with_the_count(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("vendor/\n")
    _graph(repo, ["app.py", "vendor/a.py", "vendor/sub/b.py", "vendor/c.py"])

    problems = gr.check_ignored_in_graph(repo)

    assert [(p.name, p.status) for p in problems] == [("ignored paths", "warning")]
    assert "vendor/" in problems[0].detail
    assert "3 nodes" in problems[0].detail


def test_ignored_dirs_are_reported_busiest_first_and_each_once(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("vendor/\nbuild/\n")
    _graph(repo, ["build/x.py", "vendor/a.py", "vendor/b.py", "app.py"])

    detail = gr.check_ignored_in_graph(repo)[0].detail

    assert detail.index("vendor/") < detail.index("build/")
    assert detail.count("vendor/") == 1


def test_a_root_level_ignored_file_is_not_a_directory_problem(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("secret.py\n")
    _graph(repo, ["secret.py", "app.py"])

    assert gr.check_ignored_in_graph(repo) == []


def test_absolute_source_files_inside_the_repo_are_resolved(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("vendor/\n")
    _graph(repo, [str(repo / "vendor" / "a.py"), "/elsewhere/x.py"])

    problems = gr.check_ignored_in_graph(repo)

    assert "1 nodes" in problems[0].detail


def test_edges_source_files_are_not_counted_as_nodes(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("vendor/\n")
    graph = _graph(repo, ["app.py"])
    data = json.loads(graph.read_text())
    data["links"] = [{"source": "a", "target": "b", "source_file": "vendor/e.py"}]
    graph.write_text(json.dumps(data, indent=2))

    assert gr.check_ignored_in_graph(repo) == []


def test_a_compact_graph_is_still_scanned(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("vendor/\n")
    graph = _graph(repo, ["vendor/a.py"])
    graph.write_text(json.dumps(json.loads(graph.read_text())))

    problems = gr.check_ignored_in_graph(repo)

    assert "1 nodes" in problems[0].detail


def test_a_graph_that_cannot_be_scanned_is_a_warning_not_a_crash(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    out = repo / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text("{ not json")

    problems = gr.check_ignored_in_graph(repo)

    assert [(p.name, p.status) for p in problems] == [("ignored paths", "warning")]
    assert "could not scan" in problems[0].detail


def test_no_graph_means_nothing_to_scan(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")

    assert gr.check_ignored_in_graph(repo) == []


def test_scanning_streams_the_nodes_section_without_loading_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("vendor/\n")
    _graph(repo, ["vendor/a.py"])

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("graph.json was loaded whole")

    monkeypatch.setattr(gr.json, "load", boom)

    assert "1 nodes" in gr.check_ignored_in_graph(repo)[0].detail


# --------------------------------------------------------- extension drift


def _fake_graphify(bin_dir: Path, extensions: list[str]) -> Path:
    """A `graphify` whose shebang interpreter prints `extensions` for any `-c`."""
    bin_dir.mkdir(exist_ok=True)
    interp = bin_dir / "fake-python"
    interp.write_text(f"#!/bin/sh\necho '{json.dumps(extensions)}'\n")
    interp.chmod(0o755)
    exe = bin_dir / "graphify"
    exe.write_text(f"#!{interp}\n")
    exe.chmod(0o755)
    return exe


def test_matching_extensions_are_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = _fake_graphify(tmp_path / "bin", sorted(graph_freshness.CODE_EXTENSIONS))
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")

    check = gr.check_code_extensions()

    assert (check.name, check.status) == ("code extensions", "ok")


def test_drifted_extensions_name_what_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = sorted((graph_freshness.CODE_EXTENSIONS - {".py"}) | {".zzz"})
    exe = _fake_graphify(tmp_path / "bin", installed)
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")

    check = gr.check_code_extensions()

    assert check.status == "warning"
    assert ".zzz" in check.detail
    assert ".py" in check.detail


def test_without_graphify_the_extension_check_is_skipped_with_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    check = gr.check_code_extensions()

    assert (check.name, check.status) == ("code extensions", "skipped")
    assert "graphify" in check.detail


def test_an_interpreter_that_fails_skips_the_check_instead_of_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    interp = bin_dir / "bad-python"
    interp.write_text("#!/bin/sh\nexit 3\n")
    interp.chmod(0o755)
    exe = bin_dir / "graphify"
    exe.write_text(f"#!{interp}\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    assert gr.check_code_extensions().status == "skipped"


def test_a_graphify_without_a_shebang_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "graphify"
    exe.write_bytes(b"\x7fELF-not-a-script")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    assert gr.check_code_extensions().status == "skipped"


# ------------------------------------------------------------------ collector


def _cfg(repos: list[Path]) -> Config:
    cfg = Config()
    cfg.knowledge.structure.repos = [str(r) for r in repos]
    return cfg


def _healthy(repo: Path) -> None:
    _install_hooks(repo)
    graph = _graph(repo)
    now = time.time() + 5
    os.utime(graph, (now, now))


@pytest.fixture
def no_graphify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bare = tmp_path / "bare-bin"
    bare.mkdir()
    for tool in ("git", "sh"):
        found = subprocess.run(["which", tool], capture_output=True, text=True).stdout.strip()
        (bare / tool).symlink_to(found)
    monkeypatch.setenv("PATH", str(bare))


def test_a_healthy_repo_is_one_ok_check(tmp_path: Path, no_graphify: None) -> None:
    repo = _repo(tmp_path / "repo")
    _healthy(repo)

    health = gr.collect_graph_health(_cfg([repo]), log_path=tmp_path / "none.log")

    assert len(health.repos) == 1
    assert health.repos[0].path == str(repo)
    assert [(c.name, c.status) for c in health.repos[0].checks] == [("graph", "ok")]
    assert health.repos[0].status == "ok"


def test_every_problem_is_listed_and_the_worst_status_wins(
    tmp_path: Path, no_graphify: None
) -> None:
    repo = _repo(tmp_path / "repo")
    _healthy(repo)
    (repo / ".git" / "hooks" / "post-merge").unlink()
    log = _log(tmp_path / "u.log", f"failed: {repo}: boom")

    health = gr.collect_graph_health(_cfg([repo]), log_path=log)

    repo_health = health.repos[0]
    assert sorted(_names(repo_health.checks)) == ["hooks", "last update"]
    assert repo_health.status == "error"


def test_discovered_repos_are_included_and_marked(tmp_path: Path, no_graphify: None) -> None:
    registered = _repo(tmp_path / "reg")
    found = _repo(tmp_path / "found")
    _healthy(registered)
    _healthy(found)
    gr.store_path().parent.mkdir(parents=True, exist_ok=True)
    gr.store_path().write_text(json.dumps({"discovered": [str(found)]}))

    health = gr.collect_graph_health(_cfg([registered]), log_path=tmp_path / "none.log")

    assert [(r.path, r.discovered) for r in health.repos] == [
        (str(registered), False),
        (str(found), True),
    ]


def test_a_missing_repo_directory_is_an_error_line_not_a_crash(
    tmp_path: Path, no_graphify: None
) -> None:
    gone = tmp_path / "gone"
    repo = _repo(tmp_path / "repo")
    _healthy(repo)

    health = gr.collect_graph_health(_cfg([gone, repo]), log_path=tmp_path / "none.log")

    assert health.repos[0].status == "error"
    assert "missing" in health.repos[0].checks[0].detail
    assert health.repos[1].status == "ok"


def test_a_check_that_raises_becomes_an_error_and_the_rest_still_run(
    tmp_path: Path, no_graphify: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    other = _repo(tmp_path / "other")
    _healthy(repo)
    _healthy(other)
    real = gr.check_hooks

    def flaky(root: Path) -> list[gr.HealthCheck]:
        if root == repo:
            raise RuntimeError("kaboom")
        return real(root)

    monkeypatch.setattr(gr, "check_hooks", flaky)

    health = gr.collect_graph_health(_cfg([repo, other]), log_path=tmp_path / "none.log")

    assert health.repos[0].status == "error"
    assert "kaboom" in health.repos[0].checks[0].detail
    assert health.repos[1].status == "ok"


def test_extension_drift_is_reported_once_not_per_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = _fake_graphify(tmp_path / "bin", [".zzz"])
    monkeypatch.setenv("PATH", f"{exe.parent}{os.pathsep}{os.environ['PATH']}")
    a = _repo(tmp_path / "a")
    b = _repo(tmp_path / "b")
    _healthy(a)
    _healthy(b)

    health = gr.collect_graph_health(_cfg([a, b]), log_path=tmp_path / "none.log")

    assert health.extensions.status == "warning"
    assert all("code extensions" not in _names(r.checks) for r in health.repos)


def test_an_unreadable_discovered_store_does_not_stop_the_collector(
    tmp_path: Path, no_graphify: None
) -> None:
    repo = _repo(tmp_path / "repo")
    _healthy(repo)
    gr.store_path().parent.mkdir(parents=True, exist_ok=True)
    gr.store_path().write_text("{ not json")

    health = gr.collect_graph_health(_cfg([repo]), log_path=tmp_path / "none.log")

    assert [r.status for r in health.repos] == ["ok"]


def test_the_default_log_is_the_graphify_update_log(
    tmp_path: Path, no_graphify: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    _healthy(repo)
    logs = tmp_path / "home" / ".local" / "share" / "lazy-harness" / "logs"
    logs.mkdir(parents=True)
    _log(logs / "graphify-update.log", f"failed: {repo}: boom")

    health = gr.collect_graph_health(_cfg([repo]))

    assert _names(health.repos[0].checks) == ["last update"]


def test_without_repos_in_scope_graphify_is_not_even_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> gr.HealthCheck:
        raise AssertionError("graphify was probed")

    monkeypatch.setattr(gr, "check_code_extensions", boom)

    health = gr.collect_graph_health(_cfg([]))

    assert (health.repos, health.extensions, health.error) == ([], None, "")


def test_a_collector_level_failure_is_returned_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("scope exploded")

    monkeypatch.setattr(gr, "scope", boom)

    health = gr.collect_graph_health(_cfg([_repo(tmp_path / "repo")]))

    assert health.repos == []
    assert "scope exploded" in health.error
