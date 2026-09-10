"""`lh memory decay` — propose-only marking of unreferenced learnings (ADR-040)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.memory_cmd import memory

TODAY = date.today()
OLD_SESSION = (TODAY - timedelta(days=200)).isoformat()
RECENT_SESSION = (TODAY - timedelta(days=1)).isoformat()


def _setup(tmp_path: Path, monkeypatch) -> Path:
    store = tmp_path / "knowledge"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion   = 1\nsessions  = "sessions"\nlearnings = "learnings"\n'
    )
    (tmp_path / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n[knowledge]\nroot = "' + str(store) + '"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    return store


def _write_learning(path: Path, *, origin_session: str, title: str = "Old thing") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
title: "{title}"
origin: some-repo
origin_session: {origin_session}
tags: []
scope: universal
status: active
deprecated_by: null
deprecated_on: null
deprecated_reason: null
---

## Learning

Body.
"""
    )


def test_decay_dry_run_lists_candidates_without_writing(tmp_path: Path) -> None:
    learnings = tmp_path / "learnings"
    target = learnings / "2026-03" / "old.md"
    _write_learning(target, origin_session=OLD_SESSION)
    before = target.read_text()

    result = CliRunner().invoke(memory, ["decay", "--learnings-dir", str(learnings)])

    assert result.exit_code == 0, result.output
    assert "old.md" in result.output
    assert "Dry run" in result.output
    assert target.read_text() == before


def test_decay_skips_learnings_inside_the_horizon(tmp_path: Path) -> None:
    learnings = tmp_path / "learnings"
    _write_learning(learnings / "2026-09" / "fresh.md", origin_session=RECENT_SESSION)

    result = CliRunner().invoke(memory, ["decay", "--learnings-dir", str(learnings)])

    assert result.exit_code == 0, result.output
    assert "No active learnings" in result.output


def test_decay_apply_marks_superseded(tmp_path: Path) -> None:
    learnings = tmp_path / "learnings"
    target = learnings / "2026-03" / "old.md"
    _write_learning(target, origin_session=OLD_SESSION)

    result = CliRunner().invoke(memory, ["decay", "--learnings-dir", str(learnings), "--apply"])

    assert result.exit_code == 0, result.output
    assert "Marked 1" in result.output
    assert "status: superseded" in target.read_text()


def test_decay_respects_horizon_days_flag(tmp_path: Path) -> None:
    learnings = tmp_path / "learnings"
    session = (TODAY - timedelta(days=10)).isoformat()
    _write_learning(learnings / "2026-09" / "ten-days.md", origin_session=session)

    result = CliRunner().invoke(
        memory, ["decay", "--learnings-dir", str(learnings), "--horizon-days", "5"]
    )

    assert result.exit_code == 0, result.output
    assert "ten-days.md" in result.output


def test_decay_default_learnings_dir_resolves_from_the_knowledge_store(
    tmp_path: Path, monkeypatch
) -> None:
    """Parameter-less smoke test pairing the explicit `--learnings-dir` tests
    above: default resolution must hit the same knowledge store `lh memory
    status`/`legacy-check` resolve, not `Path.cwd()`."""
    store = _setup(tmp_path, monkeypatch)
    target = store / "learnings" / "2026-03" / "old.md"
    _write_learning(target, origin_session=OLD_SESSION)

    result = CliRunner().invoke(memory, ["decay"])

    assert result.exit_code == 0, result.output
    assert "old.md" in result.output


def test_decay_reports_when_no_knowledge_store_is_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(memory, ["decay"])

    assert result.exit_code != 0
    assert "no knowledge store" in result.output.lower()
