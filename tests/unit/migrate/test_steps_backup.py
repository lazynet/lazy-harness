from pathlib import Path

from lazy_harness.migrate.state import StepStatus
from lazy_harness.migrate.steps.backup import BackupStep


def test_backup_step_copies_files(tmp_path: Path):
    src1 = tmp_path / "file1.txt"
    src1.write_text("hello")
    src2_dir = tmp_path / "subdir"
    src2_dir.mkdir()
    (src2_dir / "nested.txt").write_text("nested")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    step = BackupStep(targets=[src1, src2_dir])
    result = step.execute(backup_dir=backup_dir, dry_run=False)

    assert result.status == StepStatus.DONE
    assert (backup_dir / "file1.txt").read_text() == "hello"
    assert (backup_dir / "subdir" / "nested.txt").read_text() == "nested"


def test_backup_step_dry_run_does_nothing(tmp_path: Path):
    src = tmp_path / "file.txt"
    src.write_text("x")
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    step = BackupStep(targets=[src])
    result = step.execute(backup_dir=backup_dir, dry_run=True)

    assert result.status == StepStatus.DONE
    assert not (backup_dir / "file.txt").exists()


def test_backup_step_ignores_missing_targets(tmp_path: Path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    step = BackupStep(targets=[tmp_path / "nope"])
    result = step.execute(backup_dir=backup_dir, dry_run=False)
    assert result.status == StepStatus.DONE
