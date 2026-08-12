"""Tests for `lh knowledge graph` — the repo list that keeps code graphs fresh."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.knowledge_cmd import knowledge


def _repo(root: Path, name: str) -> Path:
    """A directory that looks like a git repo to the CLI."""
    r = root / name
    (r / ".git").mkdir(parents=True)
    return r


def _config(tmp_path: Path, repos: list[str] | None = None) -> Path:
    body = '[harness]\nversion = "1"\n[knowledge.structure]\nenabled = true\n'
    if repos is not None:
        listed = ", ".join(f'"{r}"' for r in repos)
        body += f"repos = [{listed}]\n"
    (tmp_path / "config.toml").write_text(body)
    return tmp_path / "config.toml"


def test_graph_add_registers_a_repo(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path)
    repo = _repo(tmp_path, "myrepo")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(knowledge, ["graph", "add", str(repo)])

    assert result.exit_code == 0, result.output
    from lazy_harness.core.config import load_config

    assert str(repo) in load_config(tmp_path / "config.toml").knowledge.structure.repos


def test_graph_add_rejects_a_directory_that_is_not_a_repo(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(knowledge, ["graph", "add", str(plain)])

    assert result.exit_code != 0
    assert "not a git repo" in result.output.lower()


def test_graph_add_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    """Re-adding must not grow the list — the scheduler would walk it twice."""
    _config(tmp_path)
    repo = _repo(tmp_path, "myrepo")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    runner.invoke(knowledge, ["graph", "add", str(repo)])
    runner.invoke(knowledge, ["graph", "add", str(repo)])

    from lazy_harness.core.config import load_config

    repos = load_config(tmp_path / "config.toml").knowledge.structure.repos
    assert repos.count(str(repo)) == 1


def test_graph_list_shows_registered_repos(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path, "myrepo")
    _config(tmp_path, repos=[str(repo)])
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(knowledge, ["graph", "list"])

    assert result.exit_code == 0
    assert "myrepo" in result.output


def test_graph_update_runs_graphify_for_each_repo(tmp_path: Path, monkeypatch) -> None:
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    _config(tmp_path, repos=[str(a), str(b)])
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    from lazy_harness.knowledge import graphify as gmod

    calls: list[str] = []

    def fake_run(action, target=None, timeout=600):
        calls.append(f"{action}:{target}")
        return gmod.GraphifyResult(exit_code=0, stdout="done", stderr="")

    monkeypatch.setattr(gmod, "run_graphify", fake_run)
    monkeypatch.setattr(gmod, "is_graphify_available", lambda: True)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert result.exit_code == 0, result.output
    assert calls == [f"update:{a}", f"update:{b}"]


def test_graph_update_keeps_going_when_one_repo_fails(tmp_path: Path, monkeypatch) -> None:
    """One broken repo must not stop the scheduler from refreshing the rest."""
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    _config(tmp_path, repos=[str(a), str(b)])
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    from lazy_harness.knowledge import graphify as gmod

    seen: list[str] = []

    def fake_run(action, target=None, timeout=600):
        seen.append(str(target))
        failed = str(target) == str(a)
        return gmod.GraphifyResult(
            exit_code=1 if failed else 0, stdout="", stderr="boom" if failed else ""
        )

    monkeypatch.setattr(gmod, "run_graphify", fake_run)
    monkeypatch.setattr(gmod, "is_graphify_available", lambda: True)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert seen == [str(a), str(b)]
    assert result.exit_code != 0, "a failed repo must surface a non-zero exit"


def test_graph_add_preserves_comments_and_other_sections(tmp_path: Path, monkeypatch) -> None:
    """The config is hand-maintained and version-controlled — do not rewrite it wholesale."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n'
        "[knowledge.structure]\n"
        "# why this is enabled, in a comment worth keeping\n"
        "enabled = true\n\n"
        "[memory.engram]\n"
        "# another comment\n"
        "enabled = false\n"
    )
    repo = _repo(tmp_path, "myrepo")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(knowledge, ["graph", "add", str(repo)])
    assert result.exit_code == 0, result.output

    text = cfg_path.read_text()
    assert "# why this is enabled, in a comment worth keeping" in text
    assert "# another comment" in text
    assert "[memory.engram]" in text
