"""Engram CLI wrapper — episodic memory for AI coding agents.

Pinned version: 1.15.4 (see ADR-022).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

PINNED_VERSION = "1.15.4"


@dataclass
class EngramResult:
    exit_code: int
    stdout: str
    stderr: str


def is_engram_available() -> bool:
    return shutil.which("engram") is not None


def _build_command(action: str, project: str | None = None) -> list[str]:
    cmd = ["engram", action]
    if project:
        cmd.extend(["--project", project])
    return cmd


def run_engram(action: str, project: str | None = None, timeout: int = 300) -> EngramResult:
    cmd = _build_command(action, project=project)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return EngramResult(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)
    except subprocess.TimeoutExpired:
        return EngramResult(exit_code=-1, stdout="", stderr=f"engram timed out after {timeout}s")
    except FileNotFoundError:
        return EngramResult(exit_code=-1, stdout="", stderr="engram not found in PATH")


def mcp_server_config() -> dict:
    """Declarative MCP entry for Engram (consumed by deploy_mcp_servers)."""
    return {"command": "engram", "args": ["mcp"]}


def check_version() -> tuple[bool, str]:
    """Probe `engram --version` and compare against PINNED_VERSION.

    Returns `(matches, current_version)`. `current_version` is empty string
    if the binary is missing or the version line could not be parsed.
    """
    try:
        result = subprocess.run(["engram", "--version"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""

    if result.returncode != 0:
        return False, ""

    parts = result.stdout.strip().split()
    current = parts[-1] if parts else ""
    return current == PINNED_VERSION, current
