"""Tests for knowledge directory management."""

from __future__ import annotations

from pathlib import Path


def test_ensure_knowledge_dir_creates_marker_and_subdirs(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir

    root = ensure_knowledge_dir(tmp_path / "store")
    assert (root / "knowledge.toml").is_file()
    assert (root / "sessions").is_dir()
    assert (root / "learnings").is_dir()


def test_ensure_knowledge_dir_is_idempotent(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir

    first = ensure_knowledge_dir(tmp_path / "store")
    (first / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "s"\nlearnings = "l"\n', encoding="utf-8"
    )
    second = ensure_knowledge_dir(tmp_path / "store")
    assert second == first
    assert (second / "s").is_dir()


def test_subdir_names_come_from_the_marker(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import learnings_dir, sessions_dir

    root = tmp_path / "store"
    root.mkdir()
    (root / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "logs"\nlearnings = "lessons"\n',
        encoding="utf-8",
    )
    assert sessions_dir(root).name == "logs"
    assert learnings_dir(root).name == "lessons"


def test_session_export_path_buckets_by_year_month(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir, session_export_path

    root = ensure_knowledge_dir(tmp_path / "store")
    path = session_export_path(root, "2026-08-10", "abcdef1234567890")
    assert path == root / "sessions" / "2026-08" / "2026-08-10-abcdef12.md"
    assert path.parent.is_dir()


def test_list_sessions_newest_first(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir, list_sessions

    root = ensure_knowledge_dir(tmp_path / "store")
    bucket = root / "sessions" / "2026-08"
    bucket.mkdir(parents=True)
    (bucket / "2026-08-01-aaaaaaaa.md").write_text("a", encoding="utf-8")
    (bucket / "2026-08-09-bbbbbbbb.md").write_text("b", encoding="utf-8")
    names = [p.name for p in list_sessions(root)]
    assert names == ["2026-08-09-bbbbbbbb.md", "2026-08-01-aaaaaaaa.md"]


def test_list_sessions_empty_when_absent(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir, list_sessions

    root = ensure_knowledge_dir(tmp_path / "store")
    (root / "sessions").rmdir()
    assert list_sessions(root) == []
