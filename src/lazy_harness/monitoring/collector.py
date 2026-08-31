"""Session JSONL collector — parse agent sessions into token stats."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lazy_harness.core.project_identity import main_repo_root
from lazy_harness.monitoring.pricing import calculate_cost, is_pseudo_model

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


def _repo_name(resolved: Path) -> str:
    """The name the project should be reported under for a real path.

    A linked worktree is a checkout of a repository, not a project of its
    own: reporting it by its own basename splits one repository across as
    many rows as it has branches, and understates the cost of every one of
    them. `main_repo_root` is the same rule memory keys on, so the two
    subsystems agree about what a project is.
    """
    root = main_repo_root(resolved)
    if root is not None and root.name:
        return root.name
    return resolved.name


def extract_project_name(encoded_dir: str) -> str:
    if not encoded_dir.startswith("-"):
        return encoded_dir
    raw = encoded_dir[1:]
    if not raw:
        return "(root)"
    parts = raw.split("-")

    def try_build(index: int, current_path: str) -> str | None:
        if index == len(parts):
            return current_path
        combined = parts[index]
        for j in range(index, len(parts)):
            if j > index:
                combined += "-" + parts[j]
            # Both spellings, because the encoding maps `.` to `-` alongside
            # `/`: `.worktrees` and `worktrees` arrive here identical and only
            # the filesystem can say which one was on disk.
            for name in (combined, f".{combined}"):
                candidate = os.path.join(current_path, name)
                # Descend only into directories that exist. Checking at the
                # leaf alone searched every partition of `parts` blindly,
                # which the second spelling would have squared.
                if not os.path.isdir(candidate):
                    continue
                result = try_build(j + 1, candidate)
                if result:
                    return result
        return None

    resolved = try_build(0, "/")
    if resolved:
        return _repo_name(Path(resolved))

    # Fallback: look for a known container directory (repos, projects, etc.)
    # and return everything after it as the project name.
    for i, part in enumerate(parts):
        if part in _KNOWN_CONTAINERS and i + 1 < len(parts):
            return "-".join(parts[i + 1 :])

    return parts[-1] if parts else encoded_dir


def split_cache_creation(usage: dict[str, Any]) -> tuple[int, int]:
    """Split a usage block's cache writes into (5-minute, 1-hour) tokens.

    Claude Code reports the breakdown under `usage.cache_creation` and the
    total under `cache_creation_input_tokens`; across 6,642 measured
    assistant messages the two always agree, so the breakdown is
    authoritative when present.

    A transcript written before the breakdown existed carries only the
    total. Nothing records its TTL, so it goes to the 5-minute bucket —
    the alternative invents a 2x charge on evidence we do not have.
    """
    breakdown = usage.get("cache_creation")
    if isinstance(breakdown, dict):
        return (
            breakdown.get("ephemeral_5m_input_tokens", 0),
            breakdown.get("ephemeral_1h_input_tokens", 0),
        )
    return usage.get("cache_creation_input_tokens", 0), 0


def iter_assistant_messages(filepath: Path):
    """Yield one dict per assistant message in a JSONL session file.

    Each dict has: msg_id, model, input, output, cache_read, cache_create
    (5-minute writes) and cache_create_1h (1-hour writes).
    Messages without a usage block are skipped. msg_id falls back to a
    synthetic key when the upstream JSON has no `message.id` (legacy rows).
    """
    try:
        raw = filepath.read_text()
    except OSError:
        return
    for lineno, line in enumerate(raw.splitlines()):
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
        if not usage:
            continue
        msg_id = msg.get("id") or f"{filepath.stem}:{lineno}"
        cache_create, cache_create_1h = split_cache_creation(usage)
        yield {
            "msg_id": msg_id,
            "model": msg.get("model", "unknown"),
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
            "cache_read": usage.get("cache_read_input_tokens", 0),
            "cache_create": cache_create,
            "cache_create_1h": cache_create_1h,
        }


def parse_session(filepath: Path) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_create": 0,
            "cache_create_1h": 0,
        }
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

            cache_create, cache_create_1h = split_cache_creation(usage)
            agg = aggregated[model]
            agg["input"] += usage.get("input_tokens", 0)
            agg["output"] += usage.get("output_tokens", 0)
            agg["cache_read"] += usage.get("cache_read_input_tokens", 0)
            agg["cache_create"] += cache_create
            agg["cache_create_1h"] += cache_create_1h
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
                "cache_create_1h": tokens["cache_create_1h"],
            }
        )
    return results


_TOKEN_KEYS = ("input", "output", "cache_read", "cache_create", "cache_create_1h")


@dataclass(frozen=True)
class SessionCost:
    """What one session cost, measured from its transcript on disk.

    Every field is `None` rather than `0` when it could not be measured: a
    zero enters a cost report as a fact.
    """

    cost_usd: float | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None


def session_cost_from_disk(
    projects_dir: Path,
    session_id: str,
    pricing: dict[str, dict[str, float]],
) -> SessionCost:
    """Price one session by reading the transcript the agent already wrote.

    The same file, the same `message.id` dedup and the same pricing table the
    ingest bills from, so `lh exec` and `lh metrics ingest` answer "what did
    this session cost" with one number rather than two.
    """
    per_model: dict[str, dict[str, int]] = {}
    dates: dict[str, str] = {}
    seen: set[str] = set()

    for session_file in _session_files(projects_dir, session_id):
        file_date = extract_session_date(session_file)
        for msg in iter_assistant_messages(session_file):
            if msg["msg_id"] in seen:
                continue
            seen.add(msg["msg_id"])
            agg = per_model.setdefault(msg["model"], dict.fromkeys(_TOKEN_KEYS, 0))
            dates.setdefault(msg["model"], file_date)
            for key in _TOKEN_KEYS:
                agg[key] += msg[key]

    if not per_model:
        return SessionCost()

    # `calculate_cost` answers 0.0 for a model it has no rate for, so a partial
    # sum over the priced subset would be a real number for a fictitious run.
    # Tokens are still reported: they were counted, the run just was not priced.
    unpriced = any(m not in pricing and not is_pseudo_model(m) for m in per_model)
    cost = (
        None
        if unpriced
        else round(
            sum(
                calculate_cost(model, agg, pricing, on=dates[model])
                for model, agg in per_model.items()
            ),
            6,
        )
    )
    totals = {key: sum(agg[key] for agg in per_model.values()) for key in _TOKEN_KEYS}
    return SessionCost(
        cost_usd=cost,
        prompt_tokens=(
            totals["input"]
            + totals["cache_read"]
            + totals["cache_create"]
            + totals["cache_create_1h"]
        ),
        output_tokens=totals["output"],
        cache_creation_tokens=totals["cache_create"] + totals["cache_create_1h"],
        cache_read_tokens=totals["cache_read"],
    )


def _session_files(projects_dir: Path, session_id: str) -> list[Path]:
    """Every transcript that bills to `session_id`, oldest write first.

    Subagent turns live under `<session_id>/subagents/` and the ingest folds
    them into the parent session, so a lookup that reads only
    `<session_id>.jsonl` under-reports on exactly the runs that spawned the
    most work. Both readers have to agree or the envelope and `lh status`
    disagree about the same run.
    """
    files = [
        *projects_dir.glob(f"*/{session_id}.jsonl"),
        *projects_dir.glob(f"*/{session_id}/subagents/**/*.jsonl"),
    ]
    return sorted(files, key=lambda f: f.stat().st_mtime_ns)
