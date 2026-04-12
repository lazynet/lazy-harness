import json
from pathlib import Path

from lazy_harness.migrate.executor import execute_plan
from lazy_harness.migrate.planner import build_plan
from lazy_harness.migrate.state import (
    DeployedScript,
    DetectedState,
    StepStatus,
)


def test_execute_plan_happy_path(tmp_path: Path):
    target = tmp_path / "lcc-x.sh"
    target.write_text("#!/bin/sh\n")
    link = tmp_path / "lcc-x"
    link.symlink_to(target)

    state = DetectedState(
        deployed_scripts=[DeployedScript(name="lcc-x", symlink=link, target=target)],
    )
    backup_dir = tmp_path / "backup"
    plan = build_plan(
        state,
        backup_dir=backup_dir,
        target_config=tmp_path / "cfg.toml",
        knowledge_path=tmp_path / "knowledge",
    )

    report = execute_plan(plan, dry_run=False)
    assert all(r.status == StepStatus.DONE for r in report.results)
    assert not link.is_symlink()
    assert (backup_dir / "rollback.json").is_file()
    data = json.loads((backup_dir / "rollback.json").read_text())
    assert isinstance(data, list)


def test_execute_plan_dry_run_touches_nothing(tmp_path: Path):
    target = tmp_path / "lcc-x.sh"
    target.write_text("#!/bin/sh\n")
    link = tmp_path / "lcc-x"
    link.symlink_to(target)

    state = DetectedState(
        deployed_scripts=[DeployedScript(name="lcc-x", symlink=link, target=target)],
    )
    backup_dir = tmp_path / "backup"
    plan = build_plan(
        state,
        backup_dir=backup_dir,
        target_config=tmp_path / "cfg.toml",
        knowledge_path=tmp_path / "knowledge",
    )

    report = execute_plan(plan, dry_run=True)
    assert all(r.status == StepStatus.DONE for r in report.results)
    assert link.is_symlink()
    assert not (backup_dir / "rollback.json").exists()


def test_rollback_restores_symlink(tmp_path: Path):
    from lazy_harness.migrate.rollback import apply_rollback_log

    target = tmp_path / "lcc-y.sh"
    target.write_text("#!/bin/sh\n")
    link = tmp_path / "lcc-y"
    link.symlink_to(target)

    state = DetectedState(
        deployed_scripts=[DeployedScript(name="lcc-y", symlink=link, target=target)],
    )
    backup_dir = tmp_path / "backup"
    plan = build_plan(
        state,
        backup_dir=backup_dir,
        target_config=tmp_path / "cfg.toml",
        knowledge_path=tmp_path / "knowledge",
    )
    execute_plan(plan, dry_run=False)
    assert not link.is_symlink()

    apply_rollback_log(backup_dir)
    assert link.is_symlink()
