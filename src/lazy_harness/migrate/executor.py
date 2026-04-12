from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lazy_harness.migrate.rollback import apply_rollback_log, write_rollback_log
from lazy_harness.migrate.state import MigrationPlan, StepResult, StepStatus


@dataclass
class ExecutionReport:
    results: list[StepResult] = field(default_factory=list)
    backup_dir: Path | None = None
    rolled_back: bool = False


def execute_plan(plan: MigrationPlan, *, dry_run: bool = False) -> ExecutionReport:
    """Execute each step in the plan sequentially.

    On failure, the rollback log is written and applied immediately.
    On success (or dry run), no rollback is applied.
    """
    report = ExecutionReport(backup_dir=plan.backup_dir)
    if not dry_run:
        plan.backup_dir.mkdir(parents=True, exist_ok=True)

    for step in plan.steps:
        result = step.execute(backup_dir=plan.backup_dir, dry_run=dry_run)
        report.results.append(result)
        if result.status == StepStatus.FAILED and not dry_run:
            write_rollback_log(plan.backup_dir, report.results)
            apply_rollback_log(plan.backup_dir)
            report.rolled_back = True
            return report

    if not dry_run:
        write_rollback_log(plan.backup_dir, report.results)

    return report
