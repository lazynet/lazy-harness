from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from lazy_harness.migrate.state import (
    DeployedScript,
    RollbackOp,
    StepResult,
    StepStatus,
)


@dataclass
class RemoveScriptsStep:
    scripts: list[DeployedScript] = field(default_factory=list)
    name: str = "remove-scripts"

    def describe(self) -> str:
        return f"Remove {len(self.scripts)} deployed script symlinks"

    def plan(self) -> str:
        lines = [f"Remove {len(self.scripts)} deployed scripts:"]
        for s in self.scripts:
            lines.append(f"  - {s.symlink}")
        return "\n".join(lines)

    def execute(self, backup_dir: Path, dry_run: bool = False) -> StepResult:
        result = StepResult(name=self.name, status=StepStatus.RUNNING)
        if dry_run:
            result.status = StepStatus.DONE
            result.message = f"[dry-run] would remove {len(self.scripts)} symlinks"
            return result
        try:
            for s in self.scripts:
                if not s.symlink.is_symlink():
                    continue
                target_str = os.readlink(s.symlink)
                s.symlink.unlink()
                result.rollback_ops.append(
                    RollbackOp(
                        kind="restore_symlink",
                        payload={"path": str(s.symlink), "target": target_str},
                    )
                )
            result.status = StepStatus.DONE
            result.message = f"removed {len(self.scripts)} symlinks"
        except Exception as e:  # noqa: BLE001
            result.status = StepStatus.FAILED
            result.message = f"script removal failed: {e}"
        return result
