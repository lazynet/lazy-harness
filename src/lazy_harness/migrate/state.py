from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lazy_harness.migrate.steps.base import Step


@dataclass
class ClaudeCodeSetup:
    path: Path
    has_settings: bool = False
    has_claude_md: bool = False


@dataclass
class LazyClaudecodeSetup:
    profiles: list[str] = field(default_factory=list)
    claude_dirs: dict[str, Path] = field(default_factory=dict)  # profile -> ~/.claude-<name>
    skills_dirs: dict[str, Path] = field(default_factory=dict)
    settings_paths: dict[str, Path] = field(default_factory=dict)


@dataclass
class DeployedScript:
    name: str
    symlink: Path
    target: Path | None  # None if dangling


@dataclass
class LaunchAgentInfo:
    label: str
    plist_path: Path


@dataclass
class DetectedState:
    claude_code: ClaudeCodeSetup | None = None
    lazy_claudecode: LazyClaudecodeSetup | None = None
    lazy_harness_config: Path | None = None
    deployed_scripts: list[DeployedScript] = field(default_factory=list)
    launch_agents: list[LaunchAgentInfo] = field(default_factory=list)
    knowledge_paths: list[Path] = field(default_factory=list)
    qmd_available: bool = False

    def has_existing_setup(self) -> bool:
        return any(
            [
                self.claude_code is not None,
                self.lazy_claudecode is not None,
                self.lazy_harness_config is not None,
                bool(self.deployed_scripts),
                bool(self.launch_agents),
                bool(self.knowledge_paths),
            ]
        )


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class RollbackOp:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    name: str
    status: StepStatus = StepStatus.PENDING
    message: str = ""
    rollback_ops: list[RollbackOp] = field(default_factory=list)


@dataclass
class MigrationPlan:
    backup_dir: Path
    steps: list[Step] = field(default_factory=list)

    def describe(self) -> str:
        if not self.steps:
            return "No steps planned."
        lines = [f"Plan ({len(self.steps)} steps):"]
        for i, step in enumerate(self.steps, 1):
            lines.append(f"  {i}. {step.describe()}")
        return "\n".join(lines)
