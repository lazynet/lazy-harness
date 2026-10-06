"""`resolve_launch` failure kinds — the machine-readable tag `lh exec`'s
structured failure output and `lh run`'s exit path both key off.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import (
    AgentConfig,
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
)


def _cfg(tmp_path: Path) -> Config:
    return Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type="claude-code"),
        profiles=ProfilesConfig(
            default="personal",
            items={"personal": ProfileEntry(config_dir=str(tmp_path / ".claude-personal"))},
        ),
    )


def test_a_bad_agent_flag_is_not_reported_as_unknown_profile(tmp_path: Path) -> None:
    """A typo'd `--agent` value is a bad flag, not a bad `--profile`: the two
    must not collapse onto the same `kind` (L4)."""
    from lazy_harness.agents.launch import LaunchError, resolve_launch

    cfg = _cfg(tmp_path)

    with pytest.raises(LaunchError) as excinfo:
        resolve_launch(cfg, cwd=tmp_path, agent="nope")

    assert excinfo.value.kind != "unknown-profile"


def test_a_bad_agent_flag_has_its_own_kind(tmp_path: Path) -> None:
    from lazy_harness.agents.launch import LaunchError, resolve_launch

    cfg = _cfg(tmp_path)

    with pytest.raises(LaunchError) as excinfo:
        resolve_launch(cfg, cwd=tmp_path, agent="nope")

    assert excinfo.value.kind == "unknown-agent-flag"


def _fake_claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    versions = Path.home() / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    binary = versions / "0.0.1-fake"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)


def _git(*args: str, cwd: Path) -> None:
    import subprocess

    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "init",
        cwd=repo,
    )
    return repo.resolve()


def test_an_agent_launched_in_a_repo_keeps_its_temp_files_in_the_repo_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude Code reads `CLAUDE_CODE_TMPDIR` and ignores `TMPDIR`; Codex and the
    tools it runs read `TMPDIR`. Both must name `<repo>/tmp`, and it must exist."""
    from lazy_harness.agents.launch import resolve_launch

    _fake_claude_home(tmp_path, monkeypatch)
    repo = _repo(tmp_path)
    (repo / "src").mkdir()

    plan = resolve_launch(_cfg(tmp_path), cwd=repo / "src")

    assert plan.env["TMPDIR"] == str(repo / "tmp")
    assert plan.env["CLAUDE_CODE_TMPDIR"] == str(repo / "tmp")
    assert (repo / "tmp").is_dir()


def test_a_worktree_launch_uses_the_main_checkout_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worktree is removed after merge; its temp files must not block or die
    with that removal, so they live in the main checkout like project keys do."""
    from lazy_harness.agents.launch import resolve_launch

    _fake_claude_home(tmp_path, monkeypatch)
    repo = _repo(tmp_path)
    _git("worktree", "add", "-q", ".worktrees/wt", "-b", "wt", cwd=repo)

    plan = resolve_launch(_cfg(tmp_path), cwd=repo / ".worktrees" / "wt")

    assert plan.env["TMPDIR"] == str(repo / "tmp")
    assert plan.env["CLAUDE_CODE_TMPDIR"] == str(repo / "tmp")


def test_a_launch_outside_any_repo_leaves_the_temp_dir_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents.launch import resolve_launch

    _fake_claude_home(tmp_path, monkeypatch)
    monkeypatch.setenv("TMPDIR", "/ambient/tmp")
    monkeypatch.delenv("CLAUDE_CODE_TMPDIR", raising=False)
    outside = tmp_path / "outside"
    outside.mkdir()

    plan = resolve_launch(_cfg(tmp_path), cwd=outside)

    assert plan.env["TMPDIR"] == "/ambient/tmp"
    assert "CLAUDE_CODE_TMPDIR" not in plan.env


def test_a_launch_without_an_explicit_cwd_uses_the_process_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents.launch import resolve_launch

    _fake_claude_home(tmp_path, monkeypatch)
    repo = _repo(tmp_path)
    monkeypatch.chdir(repo)

    plan = resolve_launch(_cfg(tmp_path))

    assert plan.env["TMPDIR"] == str(repo / "tmp")
