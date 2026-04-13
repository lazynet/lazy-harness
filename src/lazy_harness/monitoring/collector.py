"""Session JSONL collector — parse agent sessions into token stats."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

_KNOWN_CONTAINERS = frozenset(
    {"repos", "projects", "src", "work", "dev", "code", "workspace", "workspaces"}
)


def extract_session_date(filepath: Path) -> str:
    try:
        for line in filepath.read_text().splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                ts = obj.get("timestamp", "")
                if ts and len(ts) >= 10:
                    return ts[:10]
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return "unknown"


def extract_project_name(encoded_dir: str) -> str:
    if not encoded_dir.startswith("-"):
        return encoded_dir
    raw = encoded_dir[1:]
    if not raw:
        return "(root)"
    parts = raw.split("-")

    def try_build(index: int, current_path: str) -> str | None:
        if index == len(parts):
            return current_path if os.path.exists(current_path) else None
        combined = parts[index]
        for j in range(index, len(parts)):
            if j > index:
                combined += "-" + parts[j]
            candidate = os.path.join(current_path, combined)
            result = try_build(j + 1, candidate)
            if result:
                return result
        return None

    resolved = try_build(0, "/")
    if resolved:
        return os.path.basename(resolved)

    # Fallback: look for a known container directory (repos, projects, etc.)
    # and return everything after it as the project name.
    for i, part in enumerate(parts):
        if part in _KNOWN_CONTAINERS and i + 1 < len(parts):
            return "-".join(parts[i + 1 :])

    return parts[-1] if parts else encoded_dir


def parse_session(filepath: Path) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, int]] = defaultdict(
        lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
    )

    try:
        for line in filepath.read_text().splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "assistant":
                continue

            msg = obj.get("message", {})
            if not isinstance(msg, dict):
                continue

            usage = msg.get("usage")
            model = msg.get("model", "unknown")
            if not usage:
                continue

            agg = aggregated[model]
            agg["input"] += usage.get("input_tokens", 0)
            agg["output"] += usage.get("output_tokens", 0)
            agg["cache_read"] += usage.get("cache_read_input_tokens", 0)
            agg["cache_create"] += usage.get("cache_creation_input_tokens", 0)
    except OSError:
        return []

    session_id = filepath.stem
    session_date = extract_session_date(filepath)

    results: list[dict[str, Any]] = []
    for model, tokens in aggregated.items():
        results.append(
            {
                "session": session_id,
                "date": session_date,
                "model": model,
                "input": tokens["input"],
                "output": tokens["output"],
                "cache_read": tokens["cache_read"],
                "cache_create": tokens["cache_create"],
            }
        )
    return results
