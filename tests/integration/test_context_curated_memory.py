"""Curated memory delivery through the actual SessionStart hook wire."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import Config, ProfileEntry, load_config, save_config
from lazy_harness.core.memory_store import memory_dir_for
from lazy_harness.knowledge.marker import write_marker


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: str) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    store = tmp_path / "store"
    write_marker(store)
    cfg = Config()
    cfg.knowledge.root = str(store)
    cfg.profiles.items = {"memory": ProfileEntry(agent=agent, config_dir=str(tmp_path / "agent"))}
    cfg.profiles.default = "memory"
    cfg.context_inject.qmd_suggest_enabled = False
    cfg.context_inject.graphify_surface_enabled = False
    cfg.context_inject.last_session_enabled = False
    save_config(cfg, config_dir / "config.toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))
    return store


def _run(cwd: Path, agent: str) -> str:
    marker = "turn_id" if agent == "codex" else "prompt_id"
    result = CliRunner().invoke(
        cli,
        ["hook", "context-inject", "--profile", "memory"],
        input=json.dumps({"hook_event_name": "SessionStart", marker: "test", "cwd": str(cwd)}),
    )
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_curated_and_episodic_memory_reach_both_adapters_from_nested_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_checkout, agent: str
) -> None:
    store = _setup(tmp_path, monkeypatch, agent)
    repo = git_checkout.repo
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/team/api.git"],
        cwd=repo,
        check=True,
    )
    memory = memory_dir_for(repo, knowledge_root=store)
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("CURATED_SENTINEL\n")
    (memory / "decisions.jsonl").write_text(json.dumps({"summary": "EPISODIC_SENTINEL"}) + "\n")

    for cwd in (repo, git_checkout.subdir, git_checkout.worktree):
        body = _run(cwd, agent)
        assert "CURATED_SENTINEL" in body
        assert "EPISODIC_SENTINEL" in body
        assert str(memory / "MEMORY.md") in body


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_curated_memory_does_not_cross_project_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: str
) -> None:
    store = _setup(tmp_path, monkeypatch, agent)
    repos = [tmp_path / name / "api" for name in ("team-one", "team-two")]
    for name, repo in zip(("team-one", "team-two"), repos, strict=True):
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", f"https://github.com/{name}/api.git"],
            cwd=repo,
            check=True,
        )
        memory = memory_dir_for(repo, knowledge_root=store)
        memory.mkdir(parents=True)
        (memory / "MEMORY.md").write_text(f"CURATED_{name}\n")

    first = _run(repos[0], agent)
    second = _run(repos[1], agent)
    assert "CURATED_team-one" in first
    assert "CURATED_team-two" not in first
    assert "CURATED_team-two" in second
    assert "CURATED_team-one" not in second


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_invalid_curated_memory_reports_source_without_exception_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_checkout, agent: str
) -> None:
    store = _setup(tmp_path, monkeypatch, agent)
    repo = git_checkout.repo
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/team/api.git"],
        cwd=repo,
        check=True,
    )
    memory = memory_dir_for(repo, knowledge_root=store)
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_bytes(b"\xffinvalid")
    body = _run(repo, agent)
    assert "Curated memory" in body
    assert str(memory / "MEMORY.md") in body
    assert "unreadable" in body
    assert "UnicodeDecodeError" not in body
    assert "\ufffd" not in body


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_curated_memory_and_whole_body_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_checkout, agent: str
) -> None:
    store = _setup(tmp_path, monkeypatch, agent)
    repo = git_checkout.repo
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/team/api.git"],
        cwd=repo,
        check=True,
    )
    memory = memory_dir_for(repo, knowledge_root=store)
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("PRIORITY_SENTINEL\n" + "x" * 8000 + "\nTAIL_SENTINEL")
    (memory / "decisions.jsonl").write_text(json.dumps({"summary": "EPISODIC_SENTINEL"}) + "\n")
    body = _run(repo, agent)
    assert len(body) <= 3000
    assert "PRIORITY_SENTINEL" in body
    assert "TAIL_SENTINEL" not in body
    assert "truncated" in body
    assert str(memory / "MEMORY.md") in body


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_missing_curated_memory_is_an_empty_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_checkout, agent: str
) -> None:
    _setup(tmp_path, monkeypatch, agent)
    body = _run(git_checkout.repo, agent)
    assert "Curated memory" not in body
    assert "unreadable" not in body


@pytest.mark.parametrize("long_source", [False, True])
def test_unreadable_curated_memory_reports_without_exception_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, long_source: bool
) -> None:
    from lazy_harness.hooks.builtins.context_inject import curated_memory_context

    memory = tmp_path / ("nested" * 40 if long_source else "memory")
    memory.mkdir()
    source = memory / "MEMORY.md"
    max_chars = 300 if long_source else 3 * len(str(source)) + 3
    source.write_text("content")
    original_open = Path.open

    def deny_source(path: Path, *args: object, **kwargs: object):
        if path == source:
            raise PermissionError("SECRET_UNRELATED_PATH")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_source)
    body = curated_memory_context(memory, max_chars)
    assert "unreadable" in body
    assert body.endswith("[unreadable or invalid MEMORY.md]")
    assert ("…" in body) is long_source
    if not long_source:
        assert str(source) in body
    assert "MEMORY.md" in body
    assert "SECRET_UNRELATED_PATH" not in body
    assert len(body) <= max_chars


def test_curated_reader_never_requests_the_full_file(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.hooks.builtins.context_inject import curated_memory_context

    memory = tmp_path / "memory"
    memory.mkdir()
    source = memory / "MEMORY.md"
    source.write_text("x" * 100_000)
    original_open = Path.open
    read_sizes: list[int] = []

    class Reader:
        def __enter__(self):
            self.file = original_open(source, encoding="utf-8")
            return self

        def __exit__(self, *args: object) -> None:
            self.file.close()

        def read(self, size: int) -> str:
            read_sizes.append(size)
            return self.file.read(size)

    def tracked_open(path: Path, *args: object, **kwargs: object):
        return Reader() if path == source else original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)
    body = curated_memory_context(memory, 300)
    assert read_sizes == [301]
    assert len(body) <= 300
    assert "truncated" in body


def test_oversized_mandatory_git_section_stays_in_overall_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_checkout
) -> None:
    store = _setup(tmp_path, monkeypatch, "claude-code")
    config_path = tmp_path / "config" / "config.toml"
    cfg = load_config(config_path)
    cfg.context_inject.max_body_chars = 200
    save_config(cfg, config_path)
    repo = git_checkout.repo
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/team/api.git"],
        cwd=repo,
        check=True,
    )
    memory = memory_dir_for(repo, knowledge_root=store)
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("CURATED_SENTINEL")
    from lazy_harness.hooks.builtins import context_inject

    monkeypatch.setattr(context_inject, "git_context", lambda _: "Branch: " + "x" * 1000)
    body = _run(repo, "claude-code")
    assert len(body) <= 200
    assert "CURATED_SENTINEL" in body
    assert "truncated" in body
    assert "Source: …" in body


@pytest.mark.parametrize("budget", [-5, 0, 1, 20])
@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_final_delivery_respects_nonpositive_and_tiny_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: str, budget: int
) -> None:
    _setup(tmp_path, monkeypatch, agent)
    config_path = tmp_path / "config" / "config.toml"
    cfg = load_config(config_path)
    cfg.context_inject.max_body_chars = budget
    save_config(cfg, config_path)
    cwd = tmp_path / "empty"
    cwd.mkdir()
    marker = "turn_id" if agent == "codex" else "prompt_id"
    result = CliRunner().invoke(
        cli,
        ["hook", "context-inject", "--profile", "memory"],
        input=json.dumps({"hook_event_name": "SessionStart", marker: "test", "cwd": str(cwd)}),
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout) if result.stdout else {}
    body = payload.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert len(body) <= max(0, budget)
    if budget <= 0:
        assert body == ""
    else:
        assert body


def test_store_source_is_not_a_native_memory_link_in_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_checkout
) -> None:
    from lazy_harness.hooks.builtins._shared import resolve_memory_dir

    store = _setup(tmp_path, monkeypatch, "claude-code")
    repo = git_checkout.repo
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/team/api.git"],
        cwd=repo,
        check=True,
    )
    source = memory_dir_for(repo, knowledge_root=store) / "MEMORY.md"
    source.parent.mkdir(parents=True)
    source.write_text("CURATED_SENTINEL")
    native = (
        resolve_memory_dir(None, agent_dir=tmp_path / "agent", sessions_subdir="projects", cwd=repo)
        / "MEMORY.md"
    )
    assert source != native
    assert not os.path.islink(source)
    assert not os.path.islink(native)
    assert not native.exists()
    assert not (tmp_path / "agent" / "settings.json").exists()


def test_curated_guidance_survives_a_pending_proposal_under_small_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_checkout
) -> None:
    store = _setup(tmp_path, monkeypatch, "claude-code")
    config_path = tmp_path / "config" / "config.toml"
    cfg = load_config(config_path)
    cfg.context_inject.max_body_chars = 200
    save_config(cfg, config_path)
    repo = git_checkout.repo
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/team/api.git"],
        cwd=repo,
        check=True,
    )
    memory = memory_dir_for(repo, knowledge_root=store)
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("CURATED_PRIORITY_SENTINEL")
    (memory / "claude-md.proposal.md").write_text("## 2026-09-25\n- **Rule:** " + "x" * 1000 + "\n")
    body = _run(repo, "claude-code")
    assert len(body) <= 200
    assert "CURATED_PRIORITY_SENTINEL" in body


def test_system_banner_is_bounded_with_the_body_for_long_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_checkout
) -> None:
    _setup(tmp_path, monkeypatch, "claude-code")
    config_path = tmp_path / "config" / "config.toml"
    cfg = load_config(config_path)
    cfg.context_inject.max_body_chars = 200
    save_config(cfg, config_path)
    from lazy_harness.hooks.builtins import context_inject

    monkeypatch.setattr(context_inject, "git_context", lambda _: "Branch: " + "x" * 1000)
    result = CliRunner().invoke(
        cli,
        ["hook", "context-inject", "--profile", "memory"],
        input=json.dumps(
            {"hook_event_name": "SessionStart", "prompt_id": "test", "cwd": str(git_checkout.repo)}
        ),
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["hookSpecificOutput"]["additionalContext"]) <= 200
    assert len(payload["systemMessage"]) <= 200
    assert "truncated" in payload["systemMessage"]
