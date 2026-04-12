from pathlib import Path

from lazy_harness.migrate.state import DeployedScript, StepStatus
from lazy_harness.migrate.steps.scripts_step import RemoveScriptsStep


def test_remove_scripts_removes_symlinks(tmp_path: Path):
    target = tmp_path / "lcc-status.sh"
    target.write_text("#!/bin/sh\n")
    link = tmp_path / "lcc-status"
    link.symlink_to(target)

    scripts = [DeployedScript(name="lcc-status", symlink=link, target=target)]
    step = RemoveScriptsStep(scripts=scripts)
    result = step.execute(backup_dir=tmp_path / "backup", dry_run=False)

    assert result.status == StepStatus.DONE
    assert not link.exists() and not link.is_symlink()
    assert target.exists()
    assert any(op.kind == "restore_symlink" for op in result.rollback_ops)


def test_remove_scripts_dry_run(tmp_path: Path):
    target = tmp_path / "lcc-x.sh"
    target.write_text("#!/bin/sh\n")
    link = tmp_path / "lcc-x"
    link.symlink_to(target)

    step = RemoveScriptsStep(
        scripts=[DeployedScript(name="lcc-x", symlink=link, target=target)]
    )
    result = step.execute(backup_dir=tmp_path / "backup", dry_run=True)
    assert result.status == StepStatus.DONE
    assert link.is_symlink()


def test_remove_scripts_empty_list(tmp_path: Path):
    step = RemoveScriptsStep(scripts=[])
    result = step.execute(backup_dir=tmp_path / "backup", dry_run=False)
    assert result.status == StepStatus.DONE
    assert result.rollback_ops == []
