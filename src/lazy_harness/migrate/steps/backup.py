from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from lazy_harness.migrate.state import StepResult, StepStatus


@dataclass
class BackupStep:
    targets: list[Path] = field(default_factory=list)
    name: str = "backup"

    def describe(self) -> str:
        return f"Backup {len(self.targets)} paths"

    def plan(self) -> str:
        lines = [f"Backup {len(self.targets)} paths to backup directory:"]
        for t in self.targets:
            lines.append(f"  - {t}")
        return "\n".join(lines)

    def execute(self, backup_dir: Path, dry_run: bool = False) -> StepResult:
        result = StepResult(name=self.name, status=StepStatus.RUNNING)
        if dry_run:
            result.status = StepStatus.DONE
            result.message = f"[dry-run] would back up {len(self.targets)} paths"
            return result
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            for t in self.targets:
                if not t.exists():
                    continue
                dest = backup_dir / t.name
                if t.is_dir():
                    shutil.copytree(t, dest, symlinks=True, dirs_exist_ok=True)
                else:
                    shutil.copy2(t, dest, follow_symlinks=False)
            result.status = StepStatus.DONE
            result.message = f"backed up {len(self.targets)} paths"
        except Exception as e:  # noqa: BLE001
            result.status = StepStatus.FAILED
            result.message = f"backup failed: {e}"
        return result
