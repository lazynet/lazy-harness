from pathlib import Path

from lazy_harness.migrate.state import MigrationPlan, StepResult, StepStatus


def test_migration_plan_describe_empty():
    plan = MigrationPlan(backup_dir=Path("/tmp/x"), steps=[])
    assert "No steps" in plan.describe()


def test_step_result_defaults():
    r = StepResult(name="backup", status=StepStatus.PENDING)
    assert r.status == StepStatus.PENDING
    assert r.rollback_ops == []
