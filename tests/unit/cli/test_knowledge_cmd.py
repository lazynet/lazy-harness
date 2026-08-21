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


# --- embed: a run that ran out of time is not the same as a run that failed ---
#
# On a CPU-only box qmd embeds ~0.35 chunks/s, so a burst of ingestion needs
# more wall time than any single window allows — but progress commits per
# batch, so a timed-out run has really embedded most of what it touched.
# Reporting that as a failure is what kept AgentStationJobFailing firing for
# days over a job that was working. Measured on agents 2026-08-21: 374 chunks
# in 17m33s against a 600s budget.


def _timeout_result():
    from lazy_harness.knowledge.qmd import QmdResult

    return QmdResult(exit_code=-1, stdout="", stderr="QMD timed out after 600s", timed_out=True)


def test_embed_exits_zero_when_a_timeout_still_drained_backlog(monkeypatch) -> None:
    from lazy_harness.cli import knowledge_cmd

    monkeypatch.setattr(knowledge_cmd, "is_qmd_available", lambda: True)
    monkeypatch.setattr(knowledge_cmd, "embed", lambda **kw: _timeout_result())
    monkeypatch.setattr(knowledge_cmd, "pending_embeddings", iter([119, 69]).__next__)

    result = CliRunner().invoke(knowledge_cmd.knowledge, ["embed"])
    assert result.exit_code == 0
    assert "50" in result.output


def test_embed_exits_one_when_a_timeout_made_no_progress(monkeypatch) -> None:
    from lazy_harness.cli import knowledge_cmd

    monkeypatch.setattr(knowledge_cmd, "is_qmd_available", lambda: True)
    monkeypatch.setattr(knowledge_cmd, "embed", lambda **kw: _timeout_result())
    monkeypatch.setattr(knowledge_cmd, "pending_embeddings", iter([119, 119]).__next__)

    result = CliRunner().invoke(knowledge_cmd.knowledge, ["embed"])
    assert result.exit_code == 1


def test_embed_exits_one_when_progress_is_unknown(monkeypatch) -> None:
    """No evidence of progress is not evidence of progress."""
    from lazy_harness.cli import knowledge_cmd

    monkeypatch.setattr(knowledge_cmd, "is_qmd_available", lambda: True)
    monkeypatch.setattr(knowledge_cmd, "embed", lambda **kw: _timeout_result())
    monkeypatch.setattr(knowledge_cmd, "pending_embeddings", lambda: None)

    result = CliRunner().invoke(knowledge_cmd.knowledge, ["embed"])
    assert result.exit_code == 1


def test_embed_exits_one_on_a_real_failure_even_with_progress(monkeypatch) -> None:
    """Only a timeout is forgiven. A qmd that crashed is still a failure."""
    from lazy_harness.cli import knowledge_cmd
    from lazy_harness.knowledge.qmd import QmdResult

    monkeypatch.setattr(knowledge_cmd, "is_qmd_available", lambda: True)
    monkeypatch.setattr(
        knowledge_cmd,
        "embed",
        lambda **kw: QmdResult(exit_code=2, stdout="", stderr="model load failed"),
    )
    monkeypatch.setattr(knowledge_cmd, "pending_embeddings", iter([119, 69]).__next__)

    result = CliRunner().invoke(knowledge_cmd.knowledge, ["embed"])
    assert result.exit_code == 1


def test_embed_passes_the_timeout_flag_through(monkeypatch) -> None:
    from lazy_harness.cli import knowledge_cmd
    from lazy_harness.knowledge.qmd import QmdResult

    seen: dict[str, object] = {}

    def _embed(**kw):
        seen.update(kw)
        return QmdResult(exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(knowledge_cmd, "is_qmd_available", lambda: True)
    monkeypatch.setattr(knowledge_cmd, "embed", _embed)
    monkeypatch.setattr(knowledge_cmd, "pending_embeddings", lambda: 0)

    result = CliRunner().invoke(knowledge_cmd.knowledge, ["embed", "--timeout", "3600"])
    assert result.exit_code == 0
    assert seen["timeout"] == 3600
