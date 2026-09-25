import json
from pathlib import Path

from lazy_harness.migrate.executor import execute_plan
from lazy_harness.migrate.planner import build_plan
from lazy_harness.migrate.state import (
    DeployedScript,
    DetectedState,
    StepResult,
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


def test_rollback_unflatten_restores_symlink(tmp_path: Path):
    from lazy_harness.migrate.rollback import apply_rollback_log, write_rollback_log
    from lazy_harness.migrate.steps.flatten_step import FlattenSymlinksStep

    src = tmp_path / "repos" / "lazy-claudecode" / "profiles" / "lazy"
    src.mkdir(parents=True)
    (src / "CLAUDE.md").write_text("hello from lazy")

    profile = tmp_path / "home" / ".claude-lazy"
    profile.mkdir(parents=True)
    (profile / "CLAUDE.md").symlink_to(src / "CLAUDE.md")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    step = FlattenSymlinksStep(dirs=[profile])
    result = step.execute(backup_dir=backup_dir, dry_run=False)
    assert result.status.value == "done"

    assert not (profile / "CLAUDE.md").is_symlink()
    assert (profile / "CLAUDE.md").read_text() == "hello from lazy"

    write_rollback_log(backup_dir, [result])
    apply_rollback_log(backup_dir)

    assert (profile / "CLAUDE.md").is_symlink()
    assert (profile / "CLAUDE.md").read_text() == "hello from lazy"


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


def test_rollback_restore_file_uses_source_identity_not_basename(tmp_path: Path):
    """Exercise the real consumer: GenerateConfigStep's `restore_file` rollback
    op must recover the correct content even when another backed-up source
    shares the destination's basename elsewhere in the same backup."""
    from lazy_harness.migrate.rollback import apply_rollback_log, write_rollback_log
    from lazy_harness.migrate.steps.backup import BackupStep
    from lazy_harness.migrate.steps.config_step import GenerateConfigStep

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    decoy = other_dir / "cfg.toml"
    decoy.write_text("decoy content, not the real previous config")

    target = tmp_path / "cfg.toml"
    target.write_text("original content that must come back")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    backup_step = BackupStep(targets=[decoy, target])
    backup_result = backup_step.execute(backup_dir=backup_dir, dry_run=False)
    assert backup_result.status == StepStatus.DONE

    config_step = GenerateConfigStep(
        target=target,
        lazy_claudecode=None,
        knowledge_path=tmp_path / "knowledge",
    )
    config_result = config_step.execute(backup_dir=backup_dir, dry_run=False)
    assert config_result.status == StepStatus.DONE
    assert target.read_text() != "original content that must come back"

    write_rollback_log(backup_dir, [backup_result, config_result])
    messages = apply_rollback_log(backup_dir)

    assert target.read_text() == "original content that must come back"
    assert any("restored" in m for m in messages)


def test_rollback_restore_file_falls_back_to_legacy_basename_layout(tmp_path: Path):
    """A backup directory written before this fix has no manifest: flat
    basename files directly under backup_dir. Restoring from it must still
    work when there is no ambiguity."""
    from lazy_harness.migrate.rollback import apply_rollback_log, write_rollback_log
    from lazy_harness.migrate.state import RollbackOp

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / "cfg.toml").write_text("legacy backed up content")

    target = tmp_path / "cfg.toml"
    target.write_text("new content written by migration")

    result = StepResult(name="generate-config", status=StepStatus.DONE)
    result.rollback_ops.append(RollbackOp(kind="restore_file", payload={"path": str(target)}))
    write_rollback_log(backup_dir, [result])

    messages = apply_rollback_log(backup_dir)

    assert target.read_text() == "legacy backed up content"
    assert any("restored" in m for m in messages)


def test_rollback_restore_file_rejects_ambiguous_missing_entry(tmp_path: Path):
    """When a manifest exists but has no entry for the exact destination path,
    the rollback must say so rather than guessing from another entry."""
    from lazy_harness.migrate.rollback import apply_rollback_log, write_rollback_log
    from lazy_harness.migrate.state import RollbackOp
    from lazy_harness.migrate.steps.backup import BackupStep

    unrelated = tmp_path / "unrelated.toml"
    unrelated.write_text("unrelated content")

    target = tmp_path / "cfg.toml"
    target.write_text("current content, no backup entry exists for this path")

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    backup_step = BackupStep(targets=[unrelated])
    backup_result = backup_step.execute(backup_dir=backup_dir, dry_run=False)

    result = StepResult(name="generate-config", status=StepStatus.DONE)
    result.rollback_ops.append(RollbackOp(kind="restore_file", payload={"path": str(target)}))
    write_rollback_log(backup_dir, [backup_result, result])

    messages = apply_rollback_log(backup_dir)

    assert target.read_text() == "current content, no backup entry exists for this path"
    assert any("skipped" in m for m in messages)
