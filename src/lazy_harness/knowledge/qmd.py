"""QMD CLI wrapper — sync, embed, search."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class QmdResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass
class QmdHit:
    file: str
    title: str
    score: float


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


def mcp_server_config() -> dict:
    """Declarative MCP entry for QMD (consumed by deploy_mcp_servers)."""
    return {"command": "qmd", "args": ["mcp"]}


def query(text: str, limit: int = 3, timeout: int = 5) -> list[QmdHit]:
    """BM25 keyword search via `qmd search --json`. Top `limit` hits.

    Returns an empty list on any failure (qmd missing, timeout, parse error,
    non-zero exit). Used by context-inject to surface vault notes at session
    start without blocking on a misbehaving qmd.
    """
    cmd = ["qmd", "search", text, "--json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    hits: list[QmdHit] = []
    for entry in data[:limit]:
        if not isinstance(entry, dict):
            continue
        try:
            hits.append(
                QmdHit(
                    file=str(entry.get("file", "")),
                    title=str(entry.get("title", "")),
                    score=float(entry.get("score", 0.0)),
                )
            )
        except (TypeError, ValueError):
            continue
    return hits
