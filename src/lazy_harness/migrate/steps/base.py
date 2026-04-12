from __future__ import annotations

from pathlib import Path
from typing import Protocol

from lazy_harness.migrate.state import StepResult


class Step(Protocol):
    name: str

    def describe(self) -> str:
        ...

    def plan(self) -> str:
        """Human-readable description of what this step will do."""
        ...

    def execute(self, backup_dir: Path, dry_run: bool = False) -> StepResult:
        ...
