import json
from pathlib import Path

from lazy_harness.migrate.rollback import apply_rollback_log, write_rollback_log
from lazy_harness.migrate.state import RollbackOp, StepResult, StepStatus
from lazy_harness.migrate.steps.backup import BACKUP_MANIFEST_NAME, BackupStep


def _restore_file_log(*paths: Path) -> list[StepResult]:
    result = StepResult(name="generate-config", status=StepStatus.DONE)
    for p in paths:
        result.rollback_ops.append(RollbackOp(kind="restore_file", payload={"path": str(p)}))
    return [result]


def test_corrupted_manifest_is_not_treated_as_legacy(tmp_path: Path):
    """A present-but-invalid manifest must refuse the restore, never fall back
    to basename guessing — which could silently pick up an unrelated file."""
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / BACKUP_MANIFEST_NAME).write_text("{not valid json")
    # A file that *would* satisfy the legacy basename fallback if it fired.
    (backup_dir / "cfg.toml").write_text("wrong content from a stale legacy layout")

    target = tmp_path / "cfg.toml"
    target.write_text("current content, must not be overwritten")

    write_rollback_log(backup_dir, _restore_file_log(target))
    messages = apply_rollback_log(backup_dir)

    assert target.read_text() == "current content, must not be overwritten"
    assert any("skipped" in m for m in messages)


def test_two_legacy_restores_sharing_basename_are_both_refused(tmp_path: Path):
    """No manifest at all (true legacy backup). Two different destinations
    sharing a basename cannot be told apart from `backup_dir / basename`, so
    neither restore may proceed."""
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / "settings.json").write_text("only one of the two originals")

    dest_one = tmp_path / "one" / "settings.json"
    dest_two = tmp_path / "two" / "settings.json"
    dest_one.parent.mkdir(parents=True)
    dest_two.parent.mkdir(parents=True)
    dest_one.write_text("current one")
    dest_two.write_text("current two")

    write_rollback_log(backup_dir, _restore_file_log(dest_one, dest_two))
    messages = apply_rollback_log(backup_dir)

    assert dest_one.read_text() == "current one"
    assert dest_two.read_text() == "current two"
    assert sum("skipped" in m for m in messages) == 2


def test_legacy_restore_with_single_unambiguous_basename_still_works(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / "cfg.toml").write_text("legacy backed up content")

    target = tmp_path / "cfg.toml"
    target.write_text("new content written by migration")

    write_rollback_log(backup_dir, _restore_file_log(target))
    messages = apply_rollback_log(backup_dir)

    assert target.read_text() == "legacy backed up content"
    assert any("restored" in m for m in messages)


def test_restore_file_does_not_write_through_a_replacement_symlink(tmp_path: Path):
    """If something now occupies `dest` as a symlink, restoring must replace
    the link itself with the backed-up file, never write through it into
    whatever it points at."""
    decoy_target = tmp_path / "decoy-target.txt"
    decoy_target.write_text("must stay untouched")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    original = tmp_path / "cfg.toml"
    original.write_text("original content")

    step = BackupStep(targets=[original])
    backup_result = step.execute(backup_dir=backup_dir, dry_run=False)

    original.unlink()
    original.symlink_to(decoy_target)

    write_rollback_log(backup_dir, [backup_result, *_restore_file_log(original)])
    apply_rollback_log(backup_dir)

    assert not original.is_symlink()
    assert original.read_text() == "original content"
    assert decoy_target.read_text() == "must stay untouched"


def test_rollback_restores_directory_backup_replacing_current_artifact_type(tmp_path: Path):
    src_dir = tmp_path / "profile"
    src_dir.mkdir()
    (src_dir / "CLAUDE.md").write_text("original profile file")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    step = BackupStep(targets=[src_dir])
    backup_result = step.execute(backup_dir=backup_dir, dry_run=False)

    import shutil

    shutil.rmtree(src_dir)
    src_dir.write_text("migration replaced the directory with a plain file")

    write_rollback_log(backup_dir, [backup_result, *_restore_file_log(src_dir)])
    apply_rollback_log(backup_dir)

    assert src_dir.is_dir()
    assert (src_dir / "CLAUDE.md").read_text() == "original profile file"


def test_rollback_restores_symlink_backup_replacing_current_artifact_type(tmp_path: Path):
    real = tmp_path / "real-target"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    step = BackupStep(targets=[link])
    backup_result = step.execute(backup_dir=backup_dir, dry_run=False)

    link.unlink()
    link.write_text("migration replaced the symlink with a plain file")

    write_rollback_log(backup_dir, [backup_result, *_restore_file_log(link)])
    apply_rollback_log(backup_dir)

    assert link.is_symlink()
    assert (
        Path(json.loads((backup_dir / BACKUP_MANIFEST_NAME).read_text())["entries"][0]["target"])
        == real
    )
