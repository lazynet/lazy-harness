from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from lazy_harness.migrate.state import (
    RollbackOp,
    StepResult,
    StepStatus,
)

FLATTEN_MARKER = "lazy-claudecode"


def _should_flatten(link: Path) -> tuple[bool, str]:
    """Return (should_flatten, target_str).

    A symlink is flattened only if its resolved path contains
    '/lazy-claudecode/'. Returns (False, "") for everything else.
    """
    if not link.is_symlink():
        return False, ""
    target_str = os.readlink(link)
    try:
        resolved = link.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return False, ""
    if f"/{FLATTEN_MARKER}/" not in str(resolved):
        return False, ""
    return True, target_str


def _flatten_one(link: Path) -> str:
    """Flatten a single symlink in place. Returns the original target string."""
    target_str = os.readlink(link)
    resolved = link.resolve(strict=True)
    tmp = link.with_name(link.name + ".lazyharness.tmp")
    if tmp.exists() or tmp.is_symlink():
        if tmp.is_dir() and not tmp.is_symlink():
            shutil.rmtree(tmp)
        else:
            tmp.unlink()
    if resolved.is_dir():
        shutil.copytree(resolved, tmp, symlinks=False)
    else:
        shutil.copy2(resolved, tmp)
    link.unlink()
    tmp.rename(link)
    return target_str


@dataclass
class FlattenSymlinksStep:
    """Flatten top-level symlinks in each provided directory that point into
    a known source repo. Only symlinks whose resolved path contains
    '/lazy-claudecode/' are flattened.
    """

    dirs: list[Path] = field(default_factory=list)
    name: str = "flatten-symlinks"

    def describe(self) -> str:
        return f"Flatten lazy-claudecode symlinks in {len(self.dirs)} profile dir(s)"

    def plan(self) -> str:
        lines = [f"Flatten lazy-claudecode symlinks in {len(self.dirs)} profile dirs:"]
        for d in self.dirs:
            if not d.is_dir():
                continue
            for entry in sorted(d.iterdir()):
                should, _ = _should_flatten(entry)
                if should:
                    lines.append(f"  - {entry}")
        if len(lines) == 1:
            lines.append("  (no matching symlinks found)")
        return "\n".join(lines)

    def execute(self, backup_dir: Path, dry_run: bool = False) -> StepResult:
        result = StepResult(name=self.name, status=StepStatus.RUNNING)
        if dry_run:
            result.status = StepStatus.DONE
            result.message = f"[dry-run] would flatten symlinks in {len(self.dirs)} dirs"
            return result
        flattened = 0
        try:
            for d in self.dirs:
                if not d.is_dir():
                    continue
                for entry in sorted(d.iterdir()):
                    should, target_str = _should_flatten(entry)
                    if not should:
                        continue
                    _flatten_one(entry)
                    flattened += 1
                    result.rollback_ops.append(
                        RollbackOp(
                            kind="unflatten",
                            payload={"path": str(entry), "target": target_str},
                        )
                    )
            result.status = StepStatus.DONE
            result.message = f"flattened {flattened} symlinks"
        except Exception as e:  # noqa: BLE001
            result.status = StepStatus.FAILED
            result.message = f"flatten failed: {e}"
        return result
