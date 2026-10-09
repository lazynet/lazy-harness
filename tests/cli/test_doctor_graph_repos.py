"""Integration tests for the `Graph repos` block in `lh doctor` and its `--json`.

The collector is covered in tests/unit/knowledge/test_graph_health.py; these
pin what `lh doctor` does with it: render it, carry it in `--json`, and never
let a broken repo take doctor down or fail its exit code.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.doctor_cmd import doctor
from lazy_harness.knowledge import graph_repos as gr


@pytest.fixture(autouse=True)
def wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "300")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _repo(path: Path, *, healthy: bool = True) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "app.py").write_text("x = 1\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    out = path / "graphify-out"
    out.mkdir()
    graph = out / "graph.json"
    graph.write_text(json.dumps({"nodes": [{"id": "a", "source_file": "app.py"}], "links": []}))
    later = time.time() + 5
    os.utime(graph, (later, later))
    hooks = path / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "post-commit").write_text(f"{gr._POST_COMMIT_MARK}\n")
    (hooks / "post-checkout").write_text(f"{gr._POST_CHECKOUT_MARK}\n")
    if healthy:
        (hooks / "post-merge").write_text(f"{gr._POST_MERGE_BEGIN}\n{gr._POST_MERGE_END}\n")
    return path.resolve()


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repos: list[Path]) -> None:
    listed = ", ".join(f'"{r}"' for r in repos)
    (tmp_path / "config.toml").write_text(
        f'[harness]\nversion = "1"\n[knowledge.structure]\nrepos = [{listed}]\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))


def test_doctor_omits_graph_repos_when_no_repo_is_in_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(tmp_path, monkeypatch, [])

    result = CliRunner().invoke(doctor)

    assert "Graph repos" not in result.output
    assert result.exit_code == 0


def test_a_healthy_repo_is_one_ok_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path / "repo")
    _config(tmp_path, monkeypatch, [repo])

    result = CliRunner().invoke(doctor)

    section = result.output.split("Graph repos", 1)[1].split("\n\n", 1)[0]
    lines = [ln for ln in section.splitlines() if "repo" in ln and ln.strip()]
    assert len(lines) == 1
    assert lines[0].lstrip().startswith("✓")
    assert result.exit_code == 0


def test_a_broken_repo_lists_its_problems_without_failing_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo", healthy=False)
    _config(tmp_path, monkeypatch, [repo])

    result = CliRunner().invoke(doctor)

    section = result.output.split("Graph repos", 1)[1]
    assert "✗" in section
    assert "post-merge missing" in section
    assert result.exit_code == 0


def test_a_discovered_repo_is_marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registered = _repo(tmp_path / "reg")
    found = _repo(tmp_path / "found")
    _config(tmp_path, monkeypatch, [registered])
    gr.store_path().parent.mkdir(parents=True, exist_ok=True)
    gr.store_path().write_text(json.dumps({"discovered": [str(found)]}))

    result = CliRunner().invoke(doctor)

    found_line = next(ln for ln in result.output.splitlines() if "/found" in ln)
    assert found_line.rstrip().endswith("discovered — ok")
    reg_line = next(ln for ln in result.output.splitlines() if "/reg" in ln)
    assert not reg_line.rstrip().endswith("discovered — ok")


def test_the_extensions_line_shows_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a = _repo(tmp_path / "a")
    b = _repo(tmp_path / "b")
    _config(tmp_path, monkeypatch, [a, b])
    monkeypatch.setattr(
        gr, "check_code_extensions", lambda: gr.HealthCheck("code extensions", "warning", "drifted")
    )

    result = CliRunner().invoke(doctor)

    assert result.output.count("code extensions") == 1
    assert "drifted" in result.output


def test_text_escapes_markup_in_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path / "repo")
    _config(tmp_path, monkeypatch, [repo])
    log = gr.default_log_dir() / "graphify-update.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"[2026-10-09 09:18:10] failed: {repo}: [bold]oops[/bold]\n")

    result = CliRunner().invoke(doctor)

    assert "[bold]oops[/bold]" in result.output


def test_a_collector_failure_is_a_line_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "repo")
    _config(tmp_path, monkeypatch, [repo])

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("scope exploded")

    monkeypatch.setattr(gr, "scope", boom)

    result = CliRunner().invoke(doctor)

    assert "scope exploded" in result.output
    assert result.exit_code == 0


def test_json_carries_the_same_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path / "repo", healthy=False)
    _config(tmp_path, monkeypatch, [repo])

    result = CliRunner().invoke(doctor, ["--json"])

    payload = json.loads(result.output)["graph_repos"]
    assert payload["error"] == ""
    [entry] = payload["repos"]
    assert entry["path"] == str(repo)
    assert entry["discovered"] is False
    assert entry["status"] == "error"
    assert entry["checks"][0]["name"] == "hooks"
    assert "post-merge missing" in entry["checks"][0]["detail"]
    assert payload["extensions"]["name"] == "code extensions"
    assert result.exit_code == 0


def test_json_without_repos_has_an_empty_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(tmp_path, monkeypatch, [])

    payload = json.loads(CliRunner().invoke(doctor, ["--json"]).output)

    assert payload["graph_repos"] == {"repos": [], "extensions": None, "error": ""}
