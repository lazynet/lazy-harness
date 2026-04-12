"""Tests for knowledge directory management."""

from __future__ import annotations

from pathlib import Path


def test_ensure_knowledge_dir(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir

    kdir = tmp_path / "knowledge"
    result = ensure_knowledge_dir(str(kdir))
    assert result.is_dir()
    assert (result / "sessions").is_dir()
    assert (result / "learnings").is_dir()


def test_ensure_knowledge_dir_existing(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir

    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "sessions").mkdir()
    result = ensure_knowledge_dir(str(kdir))
    assert result.is_dir()
    assert (result / "learnings").is_dir()


def test_session_export_path(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import session_export_path

    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    result = session_export_path(kdir, "sessions", "2026-04-12", "abc12345")
    assert str(result).endswith("2026-04-12-abc12345.md")
    assert "2026-04" in str(result)


def test_list_sessions(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import list_sessions

    sessions_dir = tmp_path / "knowledge" / "sessions" / "2026-04"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "2026-04-12-abc12345.md").write_text("# test\n")
    (sessions_dir / "2026-04-11-def67890.md").write_text("# test\n")
    result = list_sessions(tmp_path / "knowledge", "sessions")
    assert len(result) == 2
