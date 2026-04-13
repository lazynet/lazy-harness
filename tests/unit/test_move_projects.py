"""Tests for the move_projects core module."""

from __future__ import annotations

from pathlib import Path

import pytest


def _make_project(profile_dir: Path, name: str, *, with_session: bool = True) -> Path:
    pdir = profile_dir / "projects" / name
    pdir.mkdir(parents=True)
    if with_session:
        (pdir / "session1.jsonl").write_text('{"type":"system"}\n')
    return pdir


def test_list_projects_returns_names_sorted(tmp_path: Path) -> None:
    from lazy_harness.core.move_projects import list_projects

    profile = tmp_path / "src"
    _make_project(profile, "-Users-x-repos-zeta")
    _make_project(profile, "-Users-x-repos-alpha")
    _make_project(profile, "-Users-x-repos-mid")

    assert list_projects(profile) == [
        "-Users-x-repos-alpha",
        "-Users-x-repos-mid",
        "-Users-x-repos-zeta",
    ]


def test_list_projects_empty(tmp_path: Path) -> None:
    from lazy_harness.core.move_projects import list_projects

    assert list_projects(tmp_path / "missing") == []
    (tmp_path / "src").mkdir()
    assert list_projects(tmp_path / "src") == []


def test_move_project_moves_directory(tmp_path: Path) -> None:
    from lazy_harness.core.move_projects import move_project

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    project = "-Users-x-repos-foo"
    _make_project(src, project)

    result = move_project(src, dst, project)
    assert result.status == "moved"
    assert not (src / "projects" / project).exists()
    assert (dst / "projects" / project / "session1.jsonl").is_file()


def test_move_project_creates_dst_projects_dir(tmp_path: Path) -> None:
    from lazy_harness.core.move_projects import move_project

    src = tmp_path / "src"
    dst = tmp_path / "dst"  # dst doesn't exist at all yet
    _make_project(src, "-foo")

    result = move_project(src, dst, "-foo")
    assert result.status == "moved"
    assert (dst / "projects").is_dir()


def test_move_project_skipped_when_source_missing(tmp_path: Path) -> None:
    from lazy_harness.core.move_projects import move_project

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()

    result = move_project(src, dst, "-not-there")
    assert result.status == "skipped-missing"


def test_move_project_skipped_on_dst_conflict(tmp_path: Path) -> None:
    from lazy_harness.core.move_projects import move_project

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_project(src, "-foo")
    _make_project(dst, "-foo")

    result = move_project(src, dst, "-foo")
    assert result.status == "skipped-conflict"
    # Source untouched
    assert (src / "projects" / "-foo" / "session1.jsonl").is_file()
    # Dest still has its own data
    assert (dst / "projects" / "-foo").is_dir()


def test_move_project_overwrite_replaces_dest(tmp_path: Path) -> None:
    from lazy_harness.core.move_projects import move_project

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src_pdir = _make_project(src, "-foo")
    (src_pdir / "marker-from-src.txt").write_text("src")
    dst_pdir = _make_project(dst, "-foo")
    (dst_pdir / "marker-from-dst.txt").write_text("dst")

    result = move_project(src, dst, "-foo", overwrite=True)
    assert result.status == "moved"
    assert (dst / "projects" / "-foo" / "marker-from-src.txt").is_file()
    assert not (dst / "projects" / "-foo" / "marker-from-dst.txt").exists()


def test_move_projects_batch_returns_per_item_results(tmp_path: Path) -> None:
    from lazy_harness.core.move_projects import move_projects

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_project(src, "-a")
    _make_project(src, "-b")
    _make_project(dst, "-b")  # conflict

    results = move_projects(src, dst, ["-a", "-b", "-missing"])
    assert [r.status for r in results] == ["moved", "skipped-conflict", "skipped-missing"]


def test_move_project_raises_move_error_on_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.core import move_projects as mp_mod
    from lazy_harness.core.move_projects import MoveError, move_project

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    _make_project(src, "-foo")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mp_mod.shutil, "move", boom)
    with pytest.raises(MoveError, match="disk full"):
        move_project(src, dst, "-foo")
