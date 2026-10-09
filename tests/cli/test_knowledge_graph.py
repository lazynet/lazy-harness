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


def test_write_repo_list_does_not_reload_the_config(tmp_path, monkeypatch) -> None:
    """All three callers already hold a loaded Config and discard it.

    Reloading inside the writer put a second `ConfigError` outside the
    callers' try/except, so a failure there surfaced as a traceback instead
    of the handled error path.
    """
    from lazy_harness.cli import knowledge_cmd
    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n[knowledge.structure]\nenabled = true\nrepos = []\n'
    )
    cfg = load_config(cfg_path)

    def explode(_path):  # noqa: ANN001, ANN202
        raise AssertionError("_write_repo_list must not load the config again")

    monkeypatch.setattr(knowledge_cmd, "load_config", explode)

    knowledge_cmd._write_repo_list(cfg_path, cfg, ["/repos/one"])

    monkeypatch.undo()
    assert load_config(cfg_path).knowledge.structure.repos == ["/repos/one"]
    assert save_config is not None


def _fake_graphify(monkeypatch, write_graph: bool):
    import json

    from lazy_harness.knowledge import graphify as gmod

    def fake_run(action, target=None, timeout=600):
        if write_graph:
            out = Path(str(target)) / "graphify-out"
            out.mkdir(exist_ok=True)
            node = {
                "id": "f",
                "label": "func()",
                "source_file": "src/m.py",
                "source_location": "L3",
                "file_type": "code",
            }
            (out / "graph.json").write_text(json.dumps({"nodes": [node], "links": []}))
        return gmod.GraphifyResult(exit_code=0, stdout="done", stderr="")

    monkeypatch.setattr(gmod, "run_graphify", fake_run)
    monkeypatch.setattr(gmod, "is_graphify_available", lambda: True)


def test_graph_update_builds_the_graph_assist_index(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.knowledge.graph_assist import load_index

    repo = _repo(tmp_path, "a")
    _config(tmp_path, repos=[str(repo)])
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_graphify(monkeypatch, write_graph=True)

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert result.exit_code == 0, result.output
    index = repo / "graphify-out" / "cache" / "lh-graph-assist.json"
    assert index.is_file()
    # Fresh against the graph it was built from, so the hook will not rebuild.
    entries = load_index(repo, deadline_s=0, clock=lambda: 0.0)
    assert entries is not None and "func" in entries


def test_graph_update_does_not_fail_a_repo_whose_index_cannot_build(
    tmp_path: Path, monkeypatch
) -> None:
    """The graph is the product; the index is a derivative the hook can rebuild."""
    repo = _repo(tmp_path, "a")
    _config(tmp_path, repos=[str(repo)])
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_graphify(monkeypatch, write_graph=False)

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert result.exit_code == 0, result.output
    assert "index" in result.output


def test_graph_update_names_the_real_cause_when_the_index_write_fails(
    tmp_path: Path, monkeypatch
) -> None:
    from lazy_harness.knowledge import graph_assist

    repo = _repo(tmp_path, "a")
    _config(tmp_path, repos=[str(repo)])
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_graphify(monkeypatch, write_graph=True)

    def disk_full(path: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(graph_assist, "write_index", disk_full)

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert result.exit_code == 0, result.output
    # Rich wraps at the terminal width, which is 80 on CI and splits the line.
    output = " ".join(result.output.split())
    assert "disk full" in output
    assert "unreadable" not in output


# ---- self-repair and scope (graph_repos) ----------------------------------


def _stub_repair(monkeypatch) -> list[Path]:
    """Replace `ensure_repo` so no test touches real hooks; records the roots."""
    from lazy_harness.knowledge import graph_repos

    seen: list[Path] = []

    def fake(root, *, log_dir=None):  # noqa: ANN001, ANN202
        seen.append(Path(root))
        return graph_repos.RepoRepair(
            root=Path(root),
            post_merge="installed",
            graphify_hooks="already",
            ignored="failed: boom",
        )

    monkeypatch.setattr(graph_repos, "ensure_repo", fake)
    return seen


def _real_repo(root: Path, name: str) -> Path:
    import subprocess

    r = root / name
    r.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    return r


def test_graph_add_repairs_the_repo(tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path)
    repo = _repo(tmp_path, "myrepo")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("COLUMNS", "300")
    seen = _stub_repair(monkeypatch)

    result = CliRunner().invoke(knowledge, ["graph", "add", str(repo)])

    assert result.exit_code == 0, result.output
    assert seen == [repo.resolve()]
    output = " ".join(result.output.split())
    assert "post-merge" in output and "installed" in output
    assert "ignored paths" in output and "boom" in output
    assert "graphify hooks" not in output, "an `already` action is silent"


def test_graph_add_repairs_an_already_registered_repo_too(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path, "myrepo")
    _config(tmp_path, repos=[str(repo)])
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    seen = _stub_repair(monkeypatch)

    result = CliRunner().invoke(knowledge, ["graph", "add", str(repo)])

    assert result.exit_code == 0, result.output
    assert seen == [repo.resolve()]


def _scope_setup(tmp_path: Path, monkeypatch, registered: list[Path]) -> None:
    _config(tmp_path, repos=[str(r) for r in registered])
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("COLUMNS", "300")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)


def _discovered_store(tmp_path: Path, *repos: Path) -> None:
    import json

    store = tmp_path / "data" / "graph-repos.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"discovered": [str(r) for r in repos]}))


def test_graph_update_repairs_each_repo_before_its_graphify_run(
    tmp_path: Path, monkeypatch
) -> None:
    a, b = _repo(tmp_path, "a"), _repo(tmp_path, "b")
    _scope_setup(tmp_path, monkeypatch, [a, b])
    from lazy_harness.knowledge import graph_repos
    from lazy_harness.knowledge import graphify as gmod

    order: list[str] = []

    def fake_repair(root, *, log_dir=None):  # noqa: ANN001, ANN202
        order.append(f"repair:{root.name}")
        return graph_repos.RepoRepair(root, "already", "already", "already")

    def fake_run(action, target=None, timeout=600):  # noqa: ANN001, ANN202
        order.append(f"update:{Path(str(target)).name}")
        return gmod.GraphifyResult(exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(graph_repos, "ensure_repo", fake_repair)
    monkeypatch.setattr(gmod, "run_graphify", fake_run)
    monkeypatch.setattr(gmod, "is_graphify_available", lambda: True)

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert result.exit_code == 0, result.output
    assert order == ["repair:a", "update:a", "repair:b", "update:b"]
    assert "post-merge" not in result.output, "nothing to report when everything is `already`"


def test_graph_update_prints_one_line_per_repair_that_was_not_already(
    tmp_path: Path, monkeypatch
) -> None:
    a = _repo(tmp_path, "a")
    _scope_setup(tmp_path, monkeypatch, [a])
    _stub_repair(monkeypatch)
    _fake_graphify(monkeypatch, write_graph=True)

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert result.exit_code == 0, result.output
    output = " ".join(result.output.split())
    assert "post-merge: installed" in output
    assert "ignored paths: failed: boom" in output
    assert "graphify hooks" not in output


def test_graph_update_walks_discovered_repos_after_the_registered_ones(
    tmp_path: Path, monkeypatch
) -> None:
    reg, disc = _repo(tmp_path, "reg"), _repo(tmp_path, "disc")
    _scope_setup(tmp_path, monkeypatch, [reg])
    _discovered_store(tmp_path, disc)
    seen = _stub_repair(monkeypatch)
    _fake_graphify(monkeypatch, write_graph=False)

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert result.exit_code == 0, result.output
    assert seen == [reg, disc]


def test_graph_update_with_nothing_registered_still_walks_discovered_repos(
    tmp_path: Path, monkeypatch
) -> None:
    disc = _repo(tmp_path, "disc")
    _scope_setup(tmp_path, monkeypatch, [])
    _discovered_store(tmp_path, disc)
    seen = _stub_repair(monkeypatch)
    _fake_graphify(monkeypatch, write_graph=False)

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert result.exit_code == 0, result.output
    assert seen == [disc]


def test_graph_update_repo_option_updates_only_that_repo_even_if_unregistered(
    tmp_path: Path, monkeypatch
) -> None:
    reg, other = _repo(tmp_path, "reg"), _repo(tmp_path, "other")
    _scope_setup(tmp_path, monkeypatch, [reg])
    seen = _stub_repair(monkeypatch)
    _fake_graphify(monkeypatch, write_graph=False)

    result = CliRunner().invoke(knowledge, ["graph", "update", "--repo", str(other)])

    assert result.exit_code == 0, result.output
    assert seen == [other.resolve()]


def test_graph_update_repo_option_rejects_a_path_that_is_not_a_repo(
    tmp_path: Path, monkeypatch
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    _scope_setup(tmp_path, monkeypatch, [])
    _stub_repair(monkeypatch)
    _fake_graphify(monkeypatch, write_graph=False)

    result = CliRunner().invoke(knowledge, ["graph", "update", "--repo", str(plain)])

    assert result.exit_code != 0
    assert "not a git repo" in result.output.lower()


def test_graph_update_without_options_runs_on_real_repos(tmp_path: Path, monkeypatch) -> None:
    """Smoke: the parameter-less path through the real repair, with git and no stubs for it."""
    repo = _real_repo(tmp_path, "real")
    _scope_setup(tmp_path, monkeypatch, [repo])
    _fake_graphify(monkeypatch, write_graph=False)
    from lazy_harness.knowledge import graph_repos

    monkeypatch.setattr(
        graph_repos, "ensure_graphify_hooks", lambda root: "failed: stubbed, no real install"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "empty.gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert result.exit_code == 0, result.output
    assert (repo / ".git" / "hooks" / "post-merge").is_file()


def test_graph_update_refreshes_the_discovered_store_from_the_metrics(
    tmp_path: Path, monkeypatch
) -> None:
    import json

    repo = _repo(tmp_path, "seen")
    (repo / "graphify-out").mkdir()
    (repo / "graphify-out" / "graph.json").write_text("{}")
    profile = tmp_path / "profile"
    (profile / "logs").mkdir(parents=True)
    (profile / "logs" / "graph_assist_metrics.jsonl").write_text(
        json.dumps({"repo": str(repo)}) + "\n"
    )
    body = (
        '[harness]\nversion = "1"\n[knowledge.structure]\nenabled = true\nrepos = []\n'
        '[profiles]\ndefault = "p"\n'
        f'[profiles.p]\nconfig_dir = "{profile}"\nagent = "claude-code"\n'
    )
    (tmp_path / "config.toml").write_text(body)
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    seen = _stub_repair(monkeypatch)
    _fake_graphify(monkeypatch, write_graph=False)

    result = CliRunner().invoke(knowledge, ["graph", "update"])

    assert result.exit_code == 0, result.output
    assert seen == [repo]
    stored = json.loads((tmp_path / "data" / "graph-repos.json").read_text())
    assert stored["discovered"] == [str(repo)]


def test_graph_list_marks_discovered_repos(tmp_path: Path, monkeypatch) -> None:
    reg, disc = _repo(tmp_path, "reg"), _repo(tmp_path, "disc")
    _scope_setup(tmp_path, monkeypatch, [reg])
    _discovered_store(tmp_path, disc)

    result = CliRunner().invoke(knowledge, ["graph", "list"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    reg_line = next(ln for ln in lines if "/reg" in ln)
    disc_line = next(ln for ln in lines if "/disc" in ln)
    assert "discovered" not in reg_line and "discovered" in disc_line


def test_graph_list_shows_discovered_repos_when_nothing_is_registered(
    tmp_path: Path, monkeypatch
) -> None:
    disc = _repo(tmp_path, "disc")
    _scope_setup(tmp_path, monkeypatch, [])
    _discovered_store(tmp_path, disc)

    result = CliRunner().invoke(knowledge, ["graph", "list"])

    assert result.exit_code == 0, result.output
    assert "disc" in result.output and "No repos registered" not in result.output
