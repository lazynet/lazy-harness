"""Graphify CLI wrapper — code structure index for AI coding agents.

Pinned version: 0.6.9 (see ADR-023).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

PINNED_VERSION = "0.6.9"


@dataclass
class GraphifyResult:
    exit_code: int
    stdout: str
    stderr: str


def is_graphify_available() -> bool:
    return shutil.which("graphify") is not None


def _build_command(action: str, target: str | None = None) -> list[str]:
    cmd = ["graphify", action]
    if target:
        cmd.append(target)
    return cmd


def run_graphify(action: str, target: str | None = None, timeout: int = 600) -> GraphifyResult:
    cmd = _build_command(action, target=target)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return GraphifyResult(
            exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr
        )
    except subprocess.TimeoutExpired:
        return GraphifyResult(
            exit_code=-1, stdout="", stderr=f"graphify timed out after {timeout}s"
        )
    except FileNotFoundError:
        return GraphifyResult(exit_code=-1, stdout="", stderr="graphify not found in PATH")


def mcp_server_config() -> dict:
    """Declarative MCP entry for Graphify (consumed by deploy_mcp_servers)."""
    return {"command": "graphify", "args": ["mcp"]}


def check_version() -> tuple[bool, str]:
    """Probe `graphify --version` and compare against PINNED_VERSION.

    Returns `(matches, current_version)`. `current_version` is empty string
    if the binary is missing or the version line could not be parsed.
    """
    try:
        result = subprocess.run(
            ["graphify", "--version"], capture_output=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""

    if result.returncode != 0:
        return False, ""

    parts = result.stdout.strip().split()
    current = parts[-1] if parts else ""
    return current == PINNED_VERSION, current
