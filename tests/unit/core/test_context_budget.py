import subprocess
from pathlib import Path

from lazy_harness.core.config import Config, ProfileEntry, ProfilesConfig
from lazy_harness.core.context_budget import inspect_context_budget


def _config(profile: Path, agent: str = "codex") -> Config:
    cfg = Config()
    cfg.agent.type = agent
    cfg.profiles = ProfilesConfig(
        default="test", items={"test": ProfileEntry(config_dir=str(profile))}
    )
    return cfg


def test_codex_counts_both_paths_for_symlink_alias(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "AGENTS.md").write_text("global\n")
    repo = tmp_path / "repo"
    nested = repo / "pkg"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "AGENTS.md").write_text("root\n")
    (nested / "AGENTS.md").symlink_to(repo / "AGENTS.md")
    (repo / "CLAUDE.md").write_text("alternative\n")

    result = inspect_context_budget(_config(profile), "test", nested, (200, 12000))

    assert [row["path"] for row in result["sources"]] == [
        str(profile / "AGENTS.md"),
        str(repo / "AGENTS.md"),
        str(nested / "AGENTS.md"),
    ]
    assert result["total_bytes"] == len(b"global\nroot\nroot\n")
    assert str(nested / "AGENTS.md") in result["aliases"]
    assert str(repo / "CLAUDE.md") in result["alternatives"]
    assert result["unknown"] == [
        "dynamic hook output",
        "skills",
        "tools",
        "Codex CLI and layered config overrides",
        "symlink alias injection multiplicity",
    ]


def test_claude_shadow_reports_agents_and_counts_claude_chain(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "CLAUDE.md").write_text("global\n")
    repo = tmp_path / "repo"
    nested = repo / "pkg"
    nested.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("root\n")
    (repo / "CLAUDE.md").write_text("shadow\n")
    (nested / "AGENTS.md").write_text("nested\n")

    result = inspect_context_budget(_config(profile, "claude-code"), "test", nested, (200, 12000))

    assert [row["path"] for row in result["sources"]] == [
        str(profile / "CLAUDE.md"),
        str(repo / "CLAUDE.md"),
    ]
    assert str(repo / "AGENTS.md") in result["shadowed"]
    assert str(nested / "AGENTS.md") in result["shadowed"]


def test_missing_global_and_nested_worktree_chain(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "AGENTS.md").write_text("parent\n")
    subprocess.run(["git", "-C", str(repo), "add", "AGENTS.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    worktree = tmp_path / "worktree"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(worktree)], check=True
    )
    nested = worktree / "pkg"
    nested.mkdir()
    (worktree / "AGENTS.md").write_text("worktree\n")

    result = inspect_context_budget(_config(profile), "test", nested, (1, 3))

    assert str(profile / "AGENTS.md") in result["missing"]
    assert [row["path"] for row in result["sources"]] == [
        str(worktree / "AGENTS.md"),
    ]
    assert result["over_limit"] is True


def test_codex_override_fallback_and_combined_cap(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "AGENTS.md").write_text("global\n")
    (profile / "config.toml").write_text(
        'project_doc_fallback_filenames = ["TEAM.md"]\nproject_doc_max_bytes = 4\n'
    )
    repo = tmp_path / "repo"
    nested = repo / "pkg"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "AGENTS.md").write_text("base\n")
    (repo / "AGENTS.override.md").write_text("override\n")
    (nested / "TEAM.md").write_text("fallback\n")

    result = inspect_context_budget(_config(profile), "test", nested, (200, 12000))

    assert [row["path"] for row in result["sources"]] == [
        str(profile / "AGENTS.md"),
        str(repo / "AGENTS.override.md"),
    ]
    assert str(repo / "AGENTS.md") in result["shadowed"]
    assert str(nested / "TEAM.md") in result["truncated"]
    assert result["total_status"] == "upper_bound_selected_readable_files"


def test_codex_zero_cap_and_empty_override(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.toml").write_text("project_doc_max_bytes = 0\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "AGENTS.override.md").write_text("")
    (repo / "AGENTS.md").write_text("fallback\n")

    result = inspect_context_budget(_config(profile), "test", repo, (200, 12000))

    assert str(repo / "AGENTS.md") in result["shadowed"]
    assert str(repo / "AGENTS.override.md") in [row["path"] for row in result["sources"]]
    assert str(repo / "AGENTS.md") not in result["truncated"]
    assert str(repo / "AGENTS.md") not in result["missing"]
    assert "Codex CLI and layered config overrides" in result["unknown"]


def test_codex_outside_git_only_checks_cwd(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    parent = tmp_path / "parent"
    cwd = parent / "child"
    cwd.mkdir(parents=True)
    (parent / "AGENTS.md").write_text("ignored\n")
    result = inspect_context_budget(_config(profile), "test", cwd, (200, 12000))
    assert not result["sources"]
    assert str(parent / "AGENTS.md") not in result["alternatives"]


def test_codex_reports_unreadable_file_separately_from_missing(tmp_path: Path, monkeypatch) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "AGENTS.md").write_text("secret\n")
    original = Path.read_bytes

    def deny(path: Path) -> bytes:
        if path == profile / "AGENTS.md":
            raise PermissionError("denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", deny)
    result = inspect_context_budget(_config(profile), "test", tmp_path, (200, 12000))
    assert str(profile / "AGENTS.md") in result["unreadable"]
    assert str(profile / "AGENTS.md") not in result["missing"]


def test_codex_does_not_call_unreadable_repository_doc_missing(tmp_path: Path, monkeypatch) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    target = repo / "AGENTS.md"
    target.write_text("unreadable\n")
    original = Path.read_bytes

    def deny(path: Path) -> bytes:
        if path == target:
            raise PermissionError("denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", deny)
    result = inspect_context_budget(_config(profile), "test", repo, (200, 12000))
    assert str(target) in result["unreadable"]
    assert str(target) not in result["missing"]


def test_codex_cap_zero_exclusion_is_not_missing(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.toml").write_text("project_doc_max_bytes = 0\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    target = repo / "AGENTS.md"
    target.write_text("excluded\n")

    result = inspect_context_budget(_config(profile), "test", repo, (200, 12000))

    assert str(target) in result["truncated"]
    assert str(target) not in result["missing"]
    assert result["total_status"] == "upper_bound_selected_readable_files"


def test_codex_unreadable_configured_fallback_is_not_missing(tmp_path: Path, monkeypatch) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.toml").write_text('project_doc_fallback_filenames = ["TEAM.md"]\n')
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    target = repo / "TEAM.md"
    target.write_text("unreadable\n")
    original = Path.read_bytes

    def deny(path: Path) -> bytes:
        if path == target:
            raise PermissionError("denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", deny)
    result = inspect_context_budget(_config(profile), "test", repo, (200, 12000))
    assert str(target) in result["unreadable"]
    assert str(repo / "AGENTS.md") not in result["missing"]


def test_codex_resolves_symlinked_cwd_against_git_root(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    repo = tmp_path / "repo"
    nested = repo / "nested"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "AGENTS.md").write_text("root\n")
    (nested / "AGENTS.md").write_text("nested\n")
    alias = tmp_path / "alias"
    alias.symlink_to(nested, target_is_directory=True)

    result = inspect_context_budget(_config(profile), "test", alias, (200, 12000))

    assert [row["path"] for row in result["sources"]] == [
        str(repo / "AGENTS.md"),
        str(nested / "AGENTS.md"),
    ]
