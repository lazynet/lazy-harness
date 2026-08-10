"""Tests for lh knowledge init/path/push."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture(autouse=True)
def _no_env_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)


def _init_git(store: Path) -> None:
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "test"],
        ["add", "-A"],
        ["commit", "-qm", "init"],
    ):
        subprocess.run(["git", "-C", str(store), *args], check=True, capture_output=True)


def test_init_creates_store_and_marker(tmp_path: Path) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    result = CliRunner().invoke(knowledge, ["init", "--root", str(tmp_path / "store")])
    assert result.exit_code == 0
    assert (tmp_path / "store" / "knowledge.toml").is_file()
    assert (tmp_path / "store" / "sessions").is_dir()
    assert (tmp_path / "store" / "learnings").is_dir()


def test_init_is_idempotent(tmp_path: Path) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    runner = CliRunner()
    runner.invoke(knowledge, ["init", "--root", str(tmp_path / "store")])
    marker = tmp_path / "store" / "knowledge.toml"
    before = marker.read_text(encoding="utf-8")
    result = runner.invoke(knowledge, ["init", "--root", str(tmp_path / "store")])
    assert result.exit_code == 0
    assert marker.read_text(encoding="utf-8") == before


def test_path_prints_absolute_learnings_dir(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    store = tmp_path / "store"
    CliRunner().invoke(knowledge, ["init", "--root", str(store)])
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))
    result = CliRunner().invoke(knowledge, ["path", "--kind", "learnings"])
    assert result.exit_code == 0
    assert result.output.strip() == str(store.resolve() / "learnings")


def test_path_defaults_to_the_root(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    store = tmp_path / "store"
    CliRunner().invoke(knowledge, ["init", "--root", str(store)])
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))
    result = CliRunner().invoke(knowledge, ["path"])
    assert result.exit_code == 0
    assert result.output.strip() == str(store.resolve())


def test_path_on_missing_marker_exits_nonzero(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(tmp_path / "nope"))
    result = CliRunner().invoke(knowledge, ["path", "--kind", "learnings"])
    assert result.exit_code == 1
    assert "knowledge.toml" in result.output


def test_push_reports_clean(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    store = tmp_path / "store"
    CliRunner().invoke(knowledge, ["init", "--root", str(store)])
    _init_git(store)

    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))
    result = CliRunner().invoke(knowledge, ["push"])
    assert result.exit_code == 0
    assert "clean" in result.output.lower()


def test_push_on_invalid_marker_exits_nonzero(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    store = tmp_path / "store"
    CliRunner().invoke(knowledge, ["init", "--root", str(store)])
    _init_git(store)
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 99\nsessions = "s"\nlearnings = "l"\n', encoding="utf-8"
    )

    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))
    result = CliRunner().invoke(knowledge, ["push"])
    assert result.exit_code == 1
    assert "invalid" in result.output.lower()
