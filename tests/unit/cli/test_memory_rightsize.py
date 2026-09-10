"""`lh memory rightsize` — every CLAUDE.md the harness can reach, in one set.

Track 1b of `specs/designs/2026-09-10-harness-improvements-design.md`.
Read-only. Reports profile contracts (`<profile config_dir>/CLAUDE.md`) plus
the CLAUDE.md of every project reachable under a configured `[profiles.*].roots`
entry, with line count, byte count, and which threshold it breaches.

Deliberately NOT filtered by whether the project already has memory in the
knowledge store: a repo with no store entry is not a repo that doesn't
matter, it's a repo nobody has instrumented yet — exactly the kind most
likely to carry an unpruned CLAUDE.md. `lazy-popopen` (987 lines / 70KB, the
repo that motivated this whole track) has no git remote and no store entry at
all, and still has to show up.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.memory_cmd import memory


def _setup(tmp_path: Path, monkeypatch, *, roots: list[Path] | None = None) -> tuple[Path, Path]:
    store = tmp_path / "knowledge"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        "[knowledge]\n"
        "version   = 1\n"
        'sessions  = "sessions"\n'
        'learnings = "learnings"\n'
        'memory    = "memory"\n'
    )
    profile = tmp_path / "profile-lazy"
    profile.mkdir()
    roots_line = ""
    if roots:
        joined = ", ".join(f'"{r}"' for r in roots)
        roots_line = f"roots = [{joined}]\n"
    (tmp_path / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        "[profiles]\n"
        'default = "lazy"\n\n'
        "[profiles.lazy]\n"
        f'config_dir = "{profile}"\n'
        f"{roots_line}\n"
        "[knowledge]\n"
        f'root = "{store}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    return store, profile


def _repo(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(
        f'[remote "origin"]\n\turl = git@github.com:o/{name}.git\n'
    )
    return root


def _known_to_store(store: Path, name: str) -> None:
    """Give the repo `name` a memory directory in the store.

    Used only to prove the *opposite* of what it sounds like: this must have
    no bearing on whether the repo's CLAUDE.md is reported.
    """
    target = store / "memory" / "github.com" / "o" / name
    target.mkdir(parents=True)
    (target / "decisions.jsonl").write_text('{"ts": "2026-09-01", "summary": "x"}\n')


def _repo_without_remote(tmp_path: Path, name: str) -> Path:
    """A checkout with no git remote — `project_key` falls back to `local/<name>`.

    `lazy-popopen`, the repo that motivated this whole track, is exactly this
    shape: no remote configured, no memory in the store.
    """
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n\tbare = false\n")
    return root


def test_rightsize_reports_a_profile_contract_over_threshold(tmp_path: Path, monkeypatch) -> None:
    _store, profile = _setup(tmp_path, monkeypatch)
    (profile / "CLAUDE.md").write_text("line\n" * 250)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "profile:lazy" in result.output
    assert "250" in result.output
    assert "1/1 over threshold" in result.output


def test_rightsize_stays_quiet_about_a_profile_contract_under_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    _store, profile = _setup(tmp_path, monkeypatch)
    (profile / "CLAUDE.md").write_text("line\n" * 50)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "0/1 over threshold" in result.output


def test_rightsize_lists_a_project_claude_md_under_a_configured_root(
    tmp_path: Path, monkeypatch
) -> None:
    repos = tmp_path / "repos"
    repos.mkdir()
    _store, _profile = _setup(tmp_path, monkeypatch, roots=[repos])
    repo = _repo(repos, "widget")
    (repo / "CLAUDE.md").write_text("line\n" * 300)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "project:github.com/o/widget" in result.output
    assert "300" in result.output


def test_rightsize_lists_a_project_even_with_no_memory_in_the_store(
    tmp_path: Path, monkeypatch
) -> None:
    """Store presence is irrelevant to whether a CLAUDE.md is reported — a
    sibling repo that *does* have store memory must not gate the one that
    doesn't."""
    repos = tmp_path / "repos"
    repos.mkdir()
    store, _profile = _setup(tmp_path, monkeypatch, roots=[repos])
    known = _repo(repos, "widget")
    (known / "CLAUDE.md").write_text("line\n" * 5)
    _known_to_store(store, "widget")
    unstored = _repo(repos, "unstored")
    (unstored / "CLAUDE.md").write_text("line\n" * 300)
    # deliberately no _known_to_store(store, "unstored")

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "project:github.com/o/widget" in result.output
    assert "project:github.com/o/unstored" in result.output
    assert "300" in result.output


def test_rightsize_lists_a_project_with_no_remote_and_no_store_memory(
    tmp_path: Path, monkeypatch
) -> None:
    """The `lazy-popopen` case: no git remote (so `project_key` falls back to
    `local/<name>`) and nothing in the knowledge store. Must still appear,
    unmangled, with its real size."""
    repos = tmp_path / "repos"
    repos.mkdir()
    _store, _profile = _setup(tmp_path, monkeypatch, roots=[repos])
    repo = _repo_without_remote(repos, "lazy-popopen")
    (repo / "CLAUDE.md").write_text("line\n" * 987)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "project:local/lazy-popopen" in result.output
    assert "987" in result.output


def test_rightsize_finds_a_claude_md_two_levels_under_a_root(tmp_path: Path, monkeypatch) -> None:
    """`~/repos/flex` groups checkouts under `apps/`, `infra/`, `mngt/`, etc. —
    a fixed one-level scan missed every one of them, including four of the
    most expensive projects of September. Discovery has to walk down to
    wherever a repo actually is, not assume a depth."""
    repos = tmp_path / "repos"
    repos.mkdir()
    _store, _profile = _setup(tmp_path, monkeypatch, roots=[repos])
    group = repos / "infra"
    group.mkdir()
    repo = _repo(group, "devops-tf-infra")
    (repo / "CLAUDE.md").write_text("line\n" * 125)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "project:github.com/o/devops-tf-infra" in result.output
    assert "125" in result.output


def test_rightsize_does_not_report_a_repos_own_nested_worktree(tmp_path: Path, monkeypatch) -> None:
    """A repo checked out with active `.worktrees/<name>` linked worktrees
    (this repo has three) must contribute exactly one row — the repo root —
    not one row per worktree found while recursing underneath it."""
    repos = tmp_path / "repos"
    repos.mkdir()
    _store, _profile = _setup(tmp_path, monkeypatch, roots=[repos])
    repo = _repo(repos, "lazy-harness")
    (repo / "CLAUDE.md").write_text("line\n" * 42)
    worktree = repo / ".worktrees" / "feat"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {repo}/.git/worktrees/feat\n")
    (worktree / "CLAUDE.md").write_text("line\n" * 999)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert result.output.count("lazy-harness") == 1
    assert "42" in result.output
    assert "999" not in result.output


def test_rightsize_does_not_descend_past_a_repos_own_root(tmp_path: Path, monkeypatch) -> None:
    """Isolates the repo-root prune from the `.worktrees` noise-name skip: a
    nested checkout under an arbitrary directory name (a submodule-style
    vendor drop, not `.worktrees`) must still be left alone once its parent
    is recognised as a repo root — 'no hace falta bajar más'."""
    repos = tmp_path / "repos"
    repos.mkdir()
    _store, _profile = _setup(tmp_path, monkeypatch, roots=[repos])
    repo = _repo(repos, "outer")
    (repo / "CLAUDE.md").write_text("line\n" * 5)
    nested = _repo(repo / "vendor", "inner")
    (nested / "CLAUDE.md").write_text("line\n" * 999)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "inner" not in result.output
    assert "999" not in result.output


def test_rightsize_does_not_descend_into_a_known_noise_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """`node_modules`, `.venv`, `graphify-out` etc. are never a repo — walking
    into them wastes time and risks a stray CLAUDE.md-shaped file from a
    dependency being reported as a project."""
    repos = tmp_path / "repos"
    repos.mkdir()
    _store, _profile = _setup(tmp_path, monkeypatch, roots=[repos])
    repo = _repo(repos, "widget")
    (repo / "CLAUDE.md").write_text("line\n" * 5)
    noisy = repo.parent / "node_modules" / "some-pkg"
    noisy.mkdir(parents=True)
    (noisy / "CLAUDE.md").write_text("line\n" * 999)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "some-pkg" not in result.output
    assert "999" not in result.output


def test_rightsize_respects_configured_claude_md_thresholds(tmp_path: Path, monkeypatch) -> None:
    store = tmp_path / "knowledge"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        "[knowledge]\n"
        "version   = 1\n"
        'sessions  = "sessions"\n'
        'learnings = "learnings"\n'
        'memory    = "memory"\n'
    )
    profile = tmp_path / "profile-lazy"
    profile.mkdir()
    (tmp_path / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        "[profiles]\n"
        'default = "lazy"\n\n'
        "[profiles.lazy]\n"
        f'config_dir = "{profile}"\n\n'
        "[knowledge]\n"
        f'root = "{store}"\n\n'
        "[hooks.pre_tool_use]\n"
        "claude_md_max_lines = 10\n"
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    (profile / "CLAUDE.md").write_text("line\n" * 20)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "1/1 over threshold" in result.output
    assert "> 10" in result.output


def test_rightsize_with_no_config_file_reports_nothing_and_does_not_crash(
    tmp_path: Path, monkeypatch
) -> None:
    """Parameterless smoke test: no --config knob exists on this command, so
    the only resolution path is the default one — an absent config.toml must
    degrade to an empty report, not a traceback."""
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path / "nowhere"))

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "No CLAUDE.md" in result.output
