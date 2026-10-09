"""Tests for `knowledge.graph_repos` — what the harness repairs in a graph repo.

Every test runs real `git` against temporary repos, with the machine's global
git config swapped for a throwaway one: `graphify hook install` and the
excludes file are both global-config-sensitive, and an unisolated run would
write into the developer's real hooks directory.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from lazy_harness.core.config import Config, ProfileEntry
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
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    return cfg


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("x\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path.resolve()


def _stub(bin_dir: Path, name: str, body: str, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / name
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def _no_graphify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PATH with git and sh but no graphify, whatever the machine has installed."""
    bare = tmp_path / "bare-bin"
    bare.mkdir(exist_ok=True)
    for tool in ("git", "sh", "env"):
        found = subprocess.run(["which", tool], capture_output=True, text=True).stdout.strip()
        (bare / tool).symlink_to(found)
    monkeypatch.setenv("PATH", str(bare))


# ---------------------------------------------------------------- git dirs


def test_common_dir_is_the_main_checkout_from_a_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))

    assert gr.git_common_dir(repo) == repo / ".git"
    assert gr.git_common_dir(wt) == repo / ".git"


def test_common_dir_is_none_outside_a_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    assert gr.git_common_dir(plain) is None


# -------------------------------------------------------------- post-merge


def _post_merge(repo: Path) -> Path:
    return repo / ".git" / "hooks" / "post-merge"


def test_post_merge_is_created_executable_with_a_marked_block(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")

    status = gr.ensure_post_merge(repo, log_dir=tmp_path / "logs")

    hook = _post_merge(repo)
    text = hook.read_text()
    assert status == "installed"
    assert text.startswith("#!/bin/sh\n")
    assert "# lazy-harness graph-begin" in text and "# lazy-harness graph-end" in text
    assert hook.stat().st_mode & stat.S_IXUSR


def test_post_merge_second_run_is_already_and_byte_identical(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    gr.ensure_post_merge(repo, log_dir=tmp_path / "logs")
    before = _post_merge(repo).read_bytes()

    status = gr.ensure_post_merge(repo, log_dir=tmp_path / "logs")

    assert status == "already"
    assert _post_merge(repo).read_bytes() == before


def test_post_merge_preserves_another_tools_hook(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    hook = _post_merge(repo)
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\necho foreign\n")
    hook.chmod(0o644)

    gr.ensure_post_merge(repo, log_dir=tmp_path / "logs")

    text = hook.read_text()
    assert text.startswith("#!/bin/sh\necho foreign\n")
    assert text.count("# lazy-harness graph-begin") == 1
    assert hook.stat().st_mode & stat.S_IXUSR, "an appended hook must stay executable"


def test_post_merge_updates_a_stale_block_instead_of_stacking_another(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    gr.ensure_post_merge(repo, log_dir=tmp_path / "old-logs")

    status = gr.ensure_post_merge(repo, log_dir=tmp_path / "new-logs")

    text = _post_merge(repo).read_text()
    assert status == "installed"
    assert text.count("# lazy-harness graph-begin") == 1
    assert "new-logs" in text and "old-logs" not in text


def _run_hook(hook: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(hook)], cwd=cwd, capture_output=True, text=True, timeout=20)


def _wait_for(path: Path, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return True
        time.sleep(0.05)
    return False


def test_post_merge_launches_the_update_for_the_main_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    seen = tmp_path / "seen.txt"
    _stub(tmp_path / "bin", "lh", f'echo "$@" > "{seen}"', monkeypatch)
    gr.ensure_post_merge(repo, log_dir=tmp_path / "logs")

    result = _run_hook(_post_merge(repo), repo)

    assert result.returncode == 0, result.stderr
    assert _wait_for(seen), "the detached update never ran"
    assert seen.read_text().strip() == f"knowledge graph update --repo {repo}"


def test_post_merge_does_nothing_in_a_linked_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
    seen = tmp_path / "seen.txt"
    _stub(tmp_path / "bin", "lh", f'echo ran > "{seen}"', monkeypatch)
    gr.ensure_post_merge(repo, log_dir=tmp_path / "logs")

    result = _run_hook(_post_merge(repo), wt)

    assert result.returncode == 0, result.stderr
    time.sleep(0.5)
    assert not seen.exists(), "a worktree merge must not trigger a full rebuild"


def test_post_merge_never_fails_the_merge_when_lh_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    gr.ensure_post_merge(repo, log_dir=tmp_path / "logs")
    _no_graphify(tmp_path, monkeypatch)

    result = _run_hook(_post_merge(repo), repo)

    assert result.returncode == 0


def test_post_merge_logs_the_update_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path / "repo")
    logs = tmp_path / "logs"
    _stub(tmp_path / "bin", "lh", "echo from-lh", monkeypatch)
    gr.ensure_post_merge(repo, log_dir=logs)

    _run_hook(_post_merge(repo), repo)

    log = logs / "graphify-post-merge.log"
    assert _wait_for(log)
    assert "from-lh" in log.read_text()


# ----------------------------------------------------------- ignored paths


def _exclude_block(repo: Path) -> list[str]:
    text = (repo / ".git" / "info" / "exclude").read_text()
    begin, end = "# lazy-harness graph-ignored-begin", "# lazy-harness graph-ignored-end"
    if begin not in text:
        return []
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return [ln for ln in body.splitlines() if ln.strip()]


def _global_excludes(isolated_git: Path, tmp_path: Path, *patterns: str) -> Path:
    excludes = tmp_path / "global-ignore"
    excludes.write_text("\n".join(patterns) + "\n")
    with isolated_git.open("a") as f:
        f.write(f"[core]\n\texcludesfile = {excludes}\n")
    return excludes


def test_ignored_block_holds_only_directories_ignored_through_the_global_file(
    tmp_path: Path, isolated_git: Path
) -> None:
    _global_excludes(isolated_git, tmp_path, "tmp/", "scratch/")
    repo = _repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("build/\n")
    for d in ("tmp", "scratch", "build", "src"):
        (repo / d).mkdir()
        (repo / d / "f.py").write_text("x = 1\n")

    status = gr.ensure_ignored(repo)

    assert status == "installed"
    assert _exclude_block(repo) == ["/scratch/", "/tmp/"]


def test_ignored_block_is_rewritten_not_appended_and_drops_stale_entries(
    tmp_path: Path, isolated_git: Path
) -> None:
    excludes = _global_excludes(isolated_git, tmp_path, "tmp/", "scratch/")
    repo = _repo(tmp_path / "repo")
    for d in ("tmp", "scratch"):
        (repo / d).mkdir()
        (repo / d / "f.py").write_text("x = 1\n")
    gr.ensure_ignored(repo)
    path = repo / ".git" / "info" / "exclude"
    first = path.read_bytes()

    again = gr.ensure_ignored(repo)

    assert again == "already"
    assert path.read_bytes() == first, "an unchanged block must not be rewritten"

    excludes.write_text("tmp/\n")

    dropped = gr.ensure_ignored(repo)

    assert dropped == "installed"
    assert _exclude_block(repo) == ["/tmp/"]
    assert path.read_text().count("graph-ignored-begin") == 1


def test_ignored_block_keeps_foreign_exclude_lines(tmp_path: Path, isolated_git: Path) -> None:
    _global_excludes(isolated_git, tmp_path, "tmp/")
    repo = _repo(tmp_path / "repo")
    (repo / "tmp").mkdir()
    (repo / "tmp" / "f.py").write_text("x = 1\n")
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text() + "my-private-dir/\n")

    gr.ensure_ignored(repo)

    assert "my-private-dir/" in exclude.read_text()


def test_ignored_block_uses_the_default_global_file_when_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xdg = tmp_path / "xdg"
    (xdg / "git").mkdir(parents=True)
    (xdg / "git" / "ignore").write_text("tmp/\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    repo = _repo(tmp_path / "repo")
    (repo / "tmp").mkdir()
    (repo / "tmp" / "f.py").write_text("x = 1\n")

    gr.ensure_ignored(repo)

    assert _exclude_block(repo) == ["/tmp/"]


def test_ignored_block_removes_itself_when_nothing_is_global_only(
    tmp_path: Path, isolated_git: Path
) -> None:
    excludes = _global_excludes(isolated_git, tmp_path, "tmp/")
    repo = _repo(tmp_path / "repo")
    (repo / "tmp").mkdir()
    (repo / "tmp" / "f.py").write_text("x = 1\n")
    gr.ensure_ignored(repo)
    excludes.write_text("")

    status = gr.ensure_ignored(repo)

    assert status == "installed"
    assert _exclude_block(repo) == []
    assert "graph-ignored-begin" not in (repo / ".git" / "info" / "exclude").read_text()


def test_ignored_block_in_a_repo_with_nothing_to_ignore_is_already(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")

    assert gr.ensure_ignored(repo) == "already"


def test_ignored_block_is_derived_from_the_main_checkout_when_given_a_worktree(
    tmp_path: Path, isolated_git: Path
) -> None:
    _global_excludes(isolated_git, tmp_path, "tmp/")
    repo = _repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
    (repo / "tmp").mkdir()
    (repo / "tmp" / "f.py").write_text("x = 1\n")

    status = gr.ensure_ignored(wt)

    assert status == "installed"
    assert _exclude_block(repo) == ["/tmp/"]


# --------------------------------------------------------- graphify hooks

_GRAPHIFY_STUB = """\
hooks="$(git rev-parse --git-path hooks)"
mkdir -p "$hooks"
echo called >> "{counter}"
printf '# graphify-hook-start\\n# graphify-hook-end\\n' >> "$hooks/post-commit"
printf '# graphify-checkout-hook-start\\n# graphify-hook-end\\n' >> "$hooks/post-checkout"
"""


def test_graphify_hooks_install_into_the_repo_even_when_hookspath_is_global(
    tmp_path: Path, isolated_git: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """graphify honours core.hooksPath, so a bare run would edit the shared dispatcher."""
    shared = tmp_path / "shared-hooks"
    shared.mkdir()
    with isolated_git.open("a") as f:
        f.write(f"[core]\n\thooksPath = {shared}\n")
    repo = _repo(tmp_path / "repo")
    counter = tmp_path / "counter"
    _stub(tmp_path / "bin", "graphify", _GRAPHIFY_STUB.format(counter=counter), monkeypatch)

    status = gr.ensure_graphify_hooks(repo)

    assert status == "installed"
    assert "# graphify-hook-start" in (repo / ".git" / "hooks" / "post-commit").read_text()
    assert list(shared.iterdir()) == [], "the shared hooks directory must stay untouched"


def test_graphify_hooks_already_present_do_not_rerun_graphify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    counter = tmp_path / "counter"
    _stub(tmp_path / "bin", "graphify", _GRAPHIFY_STUB.format(counter=counter), monkeypatch)
    gr.ensure_graphify_hooks(repo)

    status = gr.ensure_graphify_hooks(repo)

    assert status == "already"
    assert counter.read_text().count("called") == 1


def test_graphify_hooks_are_reinstalled_when_only_post_checkout_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    hooks = repo / ".git" / "hooks"
    (hooks / "post-commit").write_text("# graphify-hook-start\n# graphify-hook-end\n")
    counter = tmp_path / "counter"
    _stub(tmp_path / "bin", "graphify", _GRAPHIFY_STUB.format(counter=counter), monkeypatch)

    status = gr.ensure_graphify_hooks(repo)

    assert status == "installed"
    assert counter.exists()


def test_graphify_hooks_fail_when_graphify_is_not_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    _no_graphify(tmp_path, monkeypatch)

    status = gr.ensure_graphify_hooks(repo)

    assert status.startswith("failed: ") and "graphify" in status


def test_graphify_hooks_fail_when_the_install_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    _stub(tmp_path / "bin", "graphify", "echo boom >&2; exit 3", monkeypatch)

    status = gr.ensure_graphify_hooks(repo)

    assert status.startswith("failed: ") and "boom" in status


def test_graphify_hooks_do_not_claim_success_the_hook_file_does_not_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 0 is not proof of the effect: the marker must be read back."""
    repo = _repo(tmp_path / "repo")
    _stub(tmp_path / "bin", "graphify", "exit 0", monkeypatch)

    status = gr.ensure_graphify_hooks(repo)

    assert status.startswith("failed: ")


# ------------------------------------------------------------- ensure_repo


def test_ensure_repo_reports_each_action_and_survives_one_failing(
    tmp_path: Path, isolated_git: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _global_excludes(isolated_git, tmp_path, "tmp/")
    repo = _repo(tmp_path / "repo")
    (repo / "tmp").mkdir()
    (repo / "tmp" / "f.py").write_text("x = 1\n")
    _no_graphify(tmp_path, monkeypatch)

    result = gr.ensure_repo(repo, log_dir=tmp_path / "logs")

    assert result.root == repo
    assert result.post_merge == "installed"
    assert result.ignored == "installed"
    assert result.graphify_hooks.startswith("failed: ")
    assert result.changes() == {"post-merge": "installed", "ignored paths": "installed"} | {
        "graphify hooks": result.graphify_hooks
    }


def test_ensure_repo_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path / "repo")
    counter = tmp_path / "counter"
    _stub(tmp_path / "bin", "graphify", _GRAPHIFY_STUB.format(counter=counter), monkeypatch)
    gr.ensure_repo(repo, log_dir=tmp_path / "logs")

    second = gr.ensure_repo(repo, log_dir=tmp_path / "logs")

    assert second.changes() == {}


def test_ensure_repo_outside_a_git_repo_fails_every_action_without_running_graphify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "plain"
    (plain / ".git").mkdir(parents=True)  # looks like a repo, is not one
    counter = tmp_path / "counter"
    _stub(tmp_path / "bin", "graphify", _GRAPHIFY_STUB.format(counter=counter), monkeypatch)

    result = gr.ensure_repo(plain, log_dir=tmp_path / "logs")

    assert result.post_merge.startswith("failed: ")
    assert result.graphify_hooks.startswith("failed: ")
    assert result.ignored.startswith("failed: ")
    assert not counter.exists(), "graphify must never run where git cannot name the repo"


def test_ensure_repo_from_a_worktree_repairs_the_main_checkouts_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
    counter = tmp_path / "counter"
    _stub(tmp_path / "bin", "graphify", _GRAPHIFY_STUB.format(counter=counter), monkeypatch)

    gr.ensure_repo(wt, log_dir=tmp_path / "logs")

    assert _post_merge(repo).is_file()
    assert "# graphify-hook-start" in (repo / ".git" / "hooks" / "post-commit").read_text()


# ------------------------------------------------------------------- scope


def _cfg(profile_dirs: dict[str, Path]) -> Config:
    cfg = Config()
    cfg.profiles.default = next(iter(profile_dirs))
    cfg.profiles.items = {
        name: ProfileEntry(config_dir=str(d), agent="claude-code")
        for name, d in profile_dirs.items()
    }
    return cfg


def _graph_repo(path: Path) -> Path:
    (path / "graphify-out").mkdir(parents=True)
    (path / "graphify-out" / "graph.json").write_text("{}")
    return path.resolve()


def _metrics(profile_dir: Path, *lines: object) -> None:
    logs = profile_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "graph_assist_metrics.jsonl").open("a") as f:
        for line in lines:
            f.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def test_discovery_reads_the_repo_field_of_every_profile(tmp_path: Path) -> None:
    a, b = _graph_repo(tmp_path / "a"), _graph_repo(tmp_path / "b")
    pa, pb = tmp_path / "pa", tmp_path / "pb"
    _metrics(pa, {"repo": str(a), "reason": "stale"})
    _metrics(pb, {"repo": str(b), "reason": "hit"}, {"repo": str(a), "reason": "hit"})

    found = gr.discover_repos(_cfg({"pa": pa, "pb": pb}))

    assert sorted(found) == [a, b]


def test_discovery_skips_repos_without_a_graph(tmp_path: Path) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    pa = tmp_path / "pa"
    _metrics(pa, {"repo": str(bare), "reason": "no_graph"})

    assert gr.discover_repos(_cfg({"pa": pa})) == []


def test_discovery_skips_malformed_lines_and_wrong_json_types(tmp_path: Path) -> None:
    good = _graph_repo(tmp_path / "good")
    pa = tmp_path / "pa"
    _metrics(
        pa,
        "not json {",
        "null",
        "7",
        "[1, 2]",
        '"str"',
        '["repo", 1]',
        '"repo"',
        {"repo": None},
        {"repo": 5},
        {"repo": ["x"]},
        {"repo": ""},
        {"no_repo_key": 1},
        {"repo": str(good)},
    )

    assert gr.discover_repos(_cfg({"pa": pa})) == [good]


def test_discovery_without_any_metrics_file_is_empty(tmp_path: Path) -> None:
    assert gr.discover_repos(_cfg({"pa": tmp_path / "pa"})) == []


def test_refresh_discovered_persists_to_the_data_dir_and_accumulates(tmp_path: Path) -> None:
    a, b = _graph_repo(tmp_path / "a"), _graph_repo(tmp_path / "b")
    pa = tmp_path / "pa"
    _metrics(pa, {"repo": str(a)})
    cfg = _cfg({"pa": pa})
    gr.refresh_discovered(cfg)
    _metrics(pa, {"repo": str(b)})

    gr.refresh_discovered(cfg)

    stored = json.loads((tmp_path / "data" / "graph-repos.json").read_text())
    assert sorted(stored["discovered"]) == sorted([str(a), str(b)])
    assert sorted(gr.load_discovered()) == [a, b]


@pytest.mark.parametrize("body", ["not json", "null", "5", "[1]", '{"discovered": 5}', "{}"])
def test_load_discovered_tolerates_a_corrupt_store(tmp_path: Path, body: str) -> None:
    store = tmp_path / "data" / "graph-repos.json"
    store.parent.mkdir(parents=True)
    store.write_text(body)

    assert gr.load_discovered() == []


def test_load_discovered_drops_non_string_entries(tmp_path: Path) -> None:
    store = tmp_path / "data" / "graph-repos.json"
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({"discovered": ["/a", None, 3, ["x"], "/b"]}))

    assert gr.load_discovered() == [Path("/a"), Path("/b")]


def test_scope_is_registered_then_discovered_without_duplicates(tmp_path: Path) -> None:
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"

    scope = gr.scope([a, b], [b, c])

    assert [(s.path, s.discovered) for s in scope] == [(a, False), (b, False), (c, True)]
