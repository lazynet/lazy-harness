"""Where a project's distilled memory lives.

Twelve places built this path themselves, each appending `/ "memory"` to a
project directory derived from the absolute cwd. That directory belongs to the
agent — it holds the agent's own session transcripts, and its name encodes the
checkout's path — so memory was both a tenant in someone else's directory and
keyed by something that changes when the checkout moves.

Memory now lives in the knowledge store, keyed by the project's own identity.
The store is the only directory the framework already synchronises between
machines, which is what makes the same `MEMORY.md` readable from both.

The agent's project directory is left exactly as it is.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.project_identity import project_key


def memory_dir_for(
    cwd: Path,
    *,
    knowledge_root: Path | None,
    legacy_project_dir: Path | None = None,
) -> Path:
    """The directory holding `MEMORY.md`, `decisions.jsonl` and `failures.jsonl`.

    Falls back to the legacy location — `<agent project dir>/memory` — when
    there is no usable knowledge store. That difference matters: a machine
    without a store keeps working exactly as before, unshared, rather than
    losing sight of memory it already wrote.
    """
    if knowledge_root is not None:
        try:
            from lazy_harness.knowledge.marker import read_marker

            area = read_marker(knowledge_root).memory
        except Exception:  # noqa: BLE001 — a malformed marker must not take a session down
            area = ""
        if area:
            key = project_key(cwd)
            resolved = knowledge_root / area
            for part in key.split("/"):
                if part and part not in (".", ".."):
                    resolved = resolved / part
            return resolved

    if legacy_project_dir is not None:
        return legacy_project_dir / "memory"
    raise ValueError("no knowledge store and no legacy project dir to fall back to")
