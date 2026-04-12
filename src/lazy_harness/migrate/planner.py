from __future__ import annotations

from pathlib import Path

from lazy_harness.migrate.state import DetectedState, MigrationPlan
from lazy_harness.migrate.steps.backup import BackupStep
from lazy_harness.migrate.steps.config_step import GenerateConfigStep
from lazy_harness.migrate.steps.scripts_step import RemoveScriptsStep


def build_plan(
    state: DetectedState,
    *,
    backup_dir: Path,
    target_config: Path,
    knowledge_path: Path,
) -> MigrationPlan:
    """Build a MigrationPlan from a DetectedState.

    The plan always begins with a Backup step and a GenerateConfig step.
    Additional steps are appended based on what was detected.
    """
    plan = MigrationPlan(backup_dir=backup_dir, steps=[])

    # 1. Backup — collect everything we might touch
    backup_targets: list[Path] = []
    if state.lazy_claudecode:
        backup_targets.extend(state.lazy_claudecode.claude_dirs.values())
    if state.lazy_harness_config:
        backup_targets.append(state.lazy_harness_config)
    for s in state.deployed_scripts:
        backup_targets.append(s.symlink)
    plan.steps.append(BackupStep(targets=backup_targets))

    # 2. Generate config
    plan.steps.append(
        GenerateConfigStep(
            target=target_config,
            lazy_claudecode=state.lazy_claudecode,
            knowledge_path=knowledge_path,
        )
    )

    # 3. Remove deployed scripts
    if state.deployed_scripts:
        plan.steps.append(RemoveScriptsStep(scripts=state.deployed_scripts))

    return plan
