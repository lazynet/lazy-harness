"""Tests for the segmented CLAUDE.md generator (lh profile sync-claude-md)."""

from __future__ import annotations

from pathlib import Path


def _seed_profile(
    profiles_dir: Path,
    name: str,
    *,
    head: str | None = "# head\n",
    tail: str | None = "# tail\n",
) -> Path:
    p = profiles_dir / name
    p.mkdir(parents=True)
    if head is not None:
        (p / "CLAUDE.head.md").write_text(head)
    if tail is not None:
        (p / "CLAUDE.tail.md").write_text(tail)
    return p


def _seed_common(profiles_dir: Path, body: str = "# common\n") -> None:
    common = profiles_dir / "_common"
    common.mkdir(parents=True, exist_ok=True)
    (common / "CLAUDE.common.md").write_text(body)


def test_sync_profiles_writes_concatenation(tmp_path: Path) -> None:
    from lazy_harness.core.sync_claude import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir, body="# common rules\n")
    _seed_profile(profiles_dir, "lazy", head="# I am lazy\n", tail="# lazy ctx\n")

    results = sync_profiles(profiles_dir)

    assert len(results) == 1
    r = results[0]
    assert r.profile == "lazy"
    assert r.action == "written"

    out = (profiles_dir / "lazy" / "CLAUDE.md").read_text()
    assert "# I am lazy" in out
    assert "# common rules" in out
    assert "# lazy ctx" in out
    # head precedes common precedes tail
    assert out.index("# I am lazy") < out.index("# common rules") < out.index("# lazy ctx")


def test_sync_profiles_is_idempotent(tmp_path: Path) -> None:
    from lazy_harness.core.sync_claude import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)
    _seed_profile(profiles_dir, "lazy")

    sync_profiles(profiles_dir)
    second = sync_profiles(profiles_dir)

    assert [r.action for r in second] == ["unchanged"]


def test_sync_profiles_skips_dirs_without_segments(tmp_path: Path) -> None:
    from lazy_harness.core.sync_claude import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)
    # full segments
    _seed_profile(profiles_dir, "lazy")
    # only head, no tail → skip
    _seed_profile(profiles_dir, "partial", tail=None)
    # nothing → skip
    (profiles_dir / "flat").mkdir()
    (profiles_dir / "flat" / "CLAUDE.md").write_text("hand-written\n")

    results = sync_profiles(profiles_dir)
    by_name = {r.profile: r for r in results}

    assert by_name["lazy"].action == "written"
    assert by_name["partial"].action == "skipped"
    assert by_name["flat"].action == "skipped"
    # untouched flat CLAUDE.md was not overwritten
    assert (profiles_dir / "flat" / "CLAUDE.md").read_text() == "hand-written\n"


def test_sync_profiles_raises_when_common_missing(tmp_path: Path) -> None:
    import pytest

    from lazy_harness.core.sync_claude import SyncError, sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_profile(profiles_dir, "lazy")

    with pytest.raises(SyncError, match="CLAUDE.common.md"):
        sync_profiles(profiles_dir)


def test_sync_profiles_skips_underscore_dirs(tmp_path: Path) -> None:
    from lazy_harness.core.sync_claude import sync_profiles

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    _seed_common(profiles_dir)
    _seed_profile(profiles_dir, "lazy")
    # _common itself has head/tail seeded — must be ignored anyway
    (profiles_dir / "_common" / "CLAUDE.head.md").write_text("h\n")
    (profiles_dir / "_common" / "CLAUDE.tail.md").write_text("t\n")

    results = sync_profiles(profiles_dir)
    profiles = {r.profile for r in results}
    assert profiles == {"lazy"}
