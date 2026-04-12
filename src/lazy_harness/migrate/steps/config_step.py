from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomli_w

from lazy_harness.core.paths import contract_path
from lazy_harness.migrate.state import (
    LazyClaudecodeSetup,
    RollbackOp,
    StepResult,
    StepStatus,
)


@dataclass
class GenerateConfigStep:
    target: Path
    lazy_claudecode: LazyClaudecodeSetup | None
    knowledge_path: Path
    name: str = "generate-config"

    def describe(self) -> str:
        count = len(self.lazy_claudecode.profiles) if self.lazy_claudecode else 1
        return f"Generate config.toml with {count} profile(s)"

    def plan(self) -> str:
        return f"Write {self.target} with detected profiles and knowledge path"

    def execute(self, backup_dir: Path, dry_run: bool = False) -> StepResult:
        result = StepResult(name=self.name, status=StepStatus.RUNNING)
        data: dict = {
            "harness": {"version": "1"},
            "agent": {"type": "claude-code"},
            "profiles": {"default": "personal"},
            "knowledge": {"path": contract_path(self.knowledge_path)},
            "monitoring": {"enabled": True},
            "scheduler": {"backend": "auto"},
        }

        if self.lazy_claudecode and self.lazy_claudecode.profiles:
            data["profiles"]["default"] = self.lazy_claudecode.profiles[0]
            for name in self.lazy_claudecode.profiles:
                data["profiles"][name] = {
                    "config_dir": contract_path(self.lazy_claudecode.claude_dirs[name]),
                }
        else:
            data["profiles"]["personal"] = {"config_dir": "~/.claude-personal"}

        if dry_run:
            result.status = StepStatus.DONE
            result.message = f"[dry-run] would write {self.target}"
            return result

        try:
            self.target.parent.mkdir(parents=True, exist_ok=True)
            previous_existed = self.target.exists()
            self.target.write_bytes(tomli_w.dumps(data).encode())
            if previous_existed:
                result.rollback_ops.append(
                    RollbackOp(kind="restore_file", payload={"path": str(self.target)})
                )
            else:
                result.rollback_ops.append(
                    RollbackOp(kind="remove_file", payload={"path": str(self.target)})
                )
            result.status = StepStatus.DONE
            result.message = f"wrote {self.target}"
        except Exception as e:  # noqa: BLE001
            result.status = StepStatus.FAILED
            result.message = f"config generation failed: {e}"
        return result
