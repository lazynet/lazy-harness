"""QMD CLI wrapper — sync, embed, search."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass

# Ten minutes was the hardcoded budget until 0.46.0. It stays the default
# because it is ample wherever the embedding model gets a GPU; the agent
# station is the case that needs it raised, and now can.
DEFAULT_EMBED_TIMEOUT = 600

_PENDING = re.compile(r"^\s*Pending:\s+(\d+)\s+need embedding", re.MULTILINE)


@dataclass
class QmdResult:
    exit_code: int
    stdout: str
    stderr: str
    # `exit_code == -1` means both "timed out" and "qmd is not installed", and
    # a caller that forgives a timeout must not also forgive a missing binary.
    timed_out: bool = False


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
        return QmdResult(
            exit_code=-1, stdout="", stderr=f"QMD timed out after {timeout}s", timed_out=True
        )
    except FileNotFoundError:
        return QmdResult(exit_code=-1, stdout="", stderr="qmd not found in PATH")


def sync(collection: str | None = None, timeout: int = 300) -> QmdResult:
    return run_qmd("update", collection=collection, timeout=timeout)


def embed(collection: str | None = None, timeout: int = DEFAULT_EMBED_TIMEOUT) -> QmdResult:
    return run_qmd("embed", collection=collection, timeout=timeout)


def status() -> QmdResult:
    return run_qmd("status", timeout=30)


def pending_embeddings() -> int | None:
    """Documents awaiting a vector, or None when that cannot be established.

    Read from `qmd status` rather than from the sqlite index directly: the
    schema behind that count is qmd's private business, while the status line
    is its published surface.

    None and 0 are deliberately different. qmd drops the Pending line once
    nothing is outstanding, so an absent line means zero — but a status call
    that failed means unknown, and a caller deciding whether a run made
    progress must not read a failed probe as "backlog is clear".
    """
    result = status()
    if result.exit_code != 0:
        return None
    match = _PENDING.search(result.stdout)
    return int(match.group(1)) if match else 0


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
