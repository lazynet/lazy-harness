from __future__ import annotations

from pathlib import Path

from lazy_harness.migrate.state import StepStatus
from lazy_harness.migrate.steps.flatten_step import FlattenSymlinksStep


def _make_fake_setup(tmp_path: Path):
    """Return (src_dir, profile_dir) with a fake lazy-claudecode source tree."""
    src = tmp_path / "repos" / "lazy-claudecode" / "profiles" / "lazy"
    src.mkdir(parents=True)
    (src / "CLAUDE.md").write_text("hello from lazy")
    commands = src / "commands"
    commands.mkdir()
    (commands / "foo.md").write_text("a command")
    (commands / "bar.md").write_text("another command")

    profile = tmp_path / "home" / ".claude-lazy"
    profile.mkdir(parents=True)
    return src, profile


def test_flatten_file_symlink(tmp_path: Path):
    src, profile = _make_fake_setup(tmp_path)
    link = profile / "CLAUDE.md"
    link.symlink_to(src / "CLAUDE.md")

    step = FlattenSymlinksStep(dirs=[profile])
    result = step.execute(backup_dir=tmp_path / "bk", dry_run=False)

    assert result.status == StepStatus.DONE
    assert not link.is_symlink()
    assert link.read_text() == "hello from lazy"
    assert len(result.rollback_ops) == 1
    assert result.rollback_ops[0].kind == "unflatten"
    assert result.rollback_ops[0].payload["path"] == str(link)


def test_flatten_dir_symlink(tmp_path: Path):
    src, profile = _make_fake_setup(tmp_path)
    link = profile / "commands"
    link.symlink_to(src / "commands")

    step = FlattenSymlinksStep(dirs=[profile])
    result = step.execute(backup_dir=tmp_path / "bk", dry_run=False)

    assert result.status == StepStatus.DONE
    assert not link.is_symlink()
    assert link.is_dir()
    assert (link / "foo.md").read_text() == "a command"
    assert (link / "bar.md").read_text() == "another command"
    assert len(result.rollback_ops) == 1
    assert result.rollback_ops[0].kind == "unflatten"


def test_skip_symlink_outside_marker(tmp_path: Path):
    src, profile = _make_fake_setup(tmp_path)
    other = tmp_path / "home" / ".claude-other"
    other.mkdir(parents=True)
    (other / "file.txt").write_text("unrelated")

    link = profile / "unrelated.txt"
    link.symlink_to(other / "file.txt")

    step = FlattenSymlinksStep(dirs=[profile])
    result = step.execute(backup_dir=tmp_path / "bk", dry_run=False)

    assert result.status == StepStatus.DONE
    assert link.is_symlink()
    assert len(result.rollback_ops) == 0


def test_skip_dangling_symlink(tmp_path: Path):
    src, profile = _make_fake_setup(tmp_path)
    link = profile / "dangling"
    link.symlink_to(tmp_path / "nonexistent" / "path")

    step = FlattenSymlinksStep(dirs=[profile])
    result = step.execute(backup_dir=tmp_path / "bk", dry_run=False)

    assert result.status == StepStatus.DONE
    assert link.is_symlink()
    assert len(result.rollback_ops) == 0


def test_skip_non_symlinks(tmp_path: Path):
    src, profile = _make_fake_setup(tmp_path)
    real_file = profile / "real.txt"
    real_file.write_text("real content")
    real_dir = profile / "real_dir"
    real_dir.mkdir()

    step = FlattenSymlinksStep(dirs=[profile])
    result = step.execute(backup_dir=tmp_path / "bk", dry_run=False)

    assert result.status == StepStatus.DONE
    assert real_file.is_file() and not real_file.is_symlink()
    assert real_dir.is_dir() and not real_dir.is_symlink()
    assert len(result.rollback_ops) == 0


def test_dry_run_does_nothing(tmp_path: Path):
    src, profile = _make_fake_setup(tmp_path)
    link = profile / "CLAUDE.md"
    link.symlink_to(src / "CLAUDE.md")

    step = FlattenSymlinksStep(dirs=[profile])
    result = step.execute(backup_dir=tmp_path / "bk", dry_run=True)

    assert result.status == StepStatus.DONE
    assert link.is_symlink()
    assert len(result.rollback_ops) == 0


def test_empty_dirs_list(tmp_path: Path):
    step = FlattenSymlinksStep(dirs=[])
    result = step.execute(backup_dir=tmp_path / "bk", dry_run=False)

    assert result.status == StepStatus.DONE
    assert "0" in result.message
