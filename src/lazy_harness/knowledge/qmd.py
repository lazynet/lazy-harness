"""QMD CLI wrapper — sync, embed, search."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class QmdResult:
    exit_code: int
    stdout: str
    stderr: str


def is_qmd_available() -> bool:
    return shutil.which("qmd") is not None


def _build_command(action: str, collection: str | None = None) -> list[str]:
    cmd = ["qmd", action]
    if collection:
        cmd.extend(["--collection", collection])
    return cmd


def run_qmd(action: str, collection: str | None = None, timeout: int = 300) -> QmdResult:
    cmd = _build_command(action, collection)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return QmdResult(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)
    except subprocess.TimeoutExpired:
        return QmdResult(exit_code=-1, stdout="", stderr=f"QMD timed out after {timeout}s")
    except FileNotFoundError:
        return QmdResult(exit_code=-1, stdout="", stderr="qmd not found in PATH")


def sync(collection: str | None = None, timeout: int = 300) -> QmdResult:
    return run_qmd("update", collection=collection, timeout=timeout)


def embed(collection: str | None = None, timeout: int = 600) -> QmdResult:
    return run_qmd("embed", collection=collection, timeout=timeout)


def status() -> QmdResult:
    return run_qmd("status", timeout=30)
