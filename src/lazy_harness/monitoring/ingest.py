"""Metrics ingest pipeline.

Walks each profile's `<config_dir>/projects/` tree recursively, parses token
usage from every session JSONL (including nested subagent files), and
REBUILDS the per-profile `session_stats` rows from scratch on every run.

Two precision properties the pipeline guarantees:

1. **Cross-file message-id dedup** — Claude Code's `/resume` writes a new
   JSONL that re-includes the prior conversation. Without dedup, the shared
   prefix gets double-counted. Every assistant message has a stable
   `message.id`; we attribute it to the oldest file (by mtime) that mentions
   it and ignore every subsequent occurrence.

2. **Atomic rebuild per profile** — the profile's rows are deleted and
   re-inserted inside a single SQLite transaction. Partial failures leave
   the previous state untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lazy_harness.core.config import Config
from lazy_harness.core.paths import expand_path
from lazy_harness.core.profiles import ProfileInfo, list_profiles
from lazy_harness.monitoring.collector import (
    extract_project_name,
    extract_session_date,
    iter_assistant_messages,
)
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.pricing import calculate_cost


@dataclass
class IngestReport:
    sessions_scanned: int = 0
    sessions_updated: int = 0
    sessions_skipped: int = 0
    messages_total: int = 0
    messages_deduped: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: IngestReport) -> None:
        self.sessions_scanned += other.sessions_scanned
        self.sessions_updated += other.sessions_updated
        self.sessions_skipped += other.sessions_skipped
        self.messages_total += other.messages_total
        self.messages_deduped += other.messages_deduped
        self.errors.extend(other.errors)


def _find_session_files(
    projects_dir: Path,
    errors: list[str],
) -> list[tuple[int, Path, str, str]]:
    """Return (mtime_ns, path, project_name, session_id) for every session JSONL.

    Walks recursively but skips any file that sits under a `memory/`
    ancestor directory — those are user-owned episodic logs, not agent
    sessions. Files nested under a `<parent_uuid>/subagents/` directory are
    attributed to the parent session_id so subagent turns fold into the
    parent session's totals instead of creating fake session rows.
    """
    files: list[tuple[int, Path, str, str]] = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = extract_project_name(project_dir.name)
        for f in project_dir.rglob("*.jsonl"):
            rel_parts = f.relative_to(project_dir).parts
            if "memory" in rel_parts[:-1]:
                continue
            if "subagents" in rel_parts[:-1]:
                session_id = rel_parts[0]
            else:
                session_id = f.stem
            try:
                mtime_ns = f.stat().st_mtime_ns
            except OSError as e:
                errors.append(f"{f}: {e}")
                continue
            files.append((mtime_ns, f, project_name, session_id))
    files.sort(key=lambda t: t[0])
    return files


def ingest_profile(
    profile: ProfileInfo,
    db: MetricsDB,
    pricing: dict[str, dict[str, float]],
) -> IngestReport:
    report = IngestReport()
    projects_dir = profile.config_dir / "projects"
    if not projects_dir.is_dir():
        return report

    files = _find_session_files(projects_dir, report.errors)

    seen_msg_ids: set[str] = set()
    # (session_id, model) -> aggregate
    aggregated: dict[tuple[str, str], dict] = {}

    for _mtime_ns, session_file, project_name, session_id in files:
        report.sessions_scanned += 1

        try:
            messages = list(iter_assistant_messages(session_file))
        except OSError as e:
            report.errors.append(f"{session_file}: {e}")
            continue

        if not messages:
            continue

        session_date = extract_session_date(session_file)
        novel_for_this_file = 0
        for m in messages:
            report.messages_total += 1
            if m["msg_id"] in seen_msg_ids:
                report.messages_deduped += 1
                continue
            seen_msg_ids.add(m["msg_id"])
            novel_for_this_file += 1
            key = (session_id, m["model"])
            agg = aggregated.get(key)
            if agg is None:
                agg = {
                    "input": 0,
                    "output": 0,
                    "cache_read": 0,
                    "cache_create": 0,
                    "date": session_date,
                    "project": project_name,
                }
                aggregated[key] = agg
            agg["input"] += m["input"]
            agg["output"] += m["output"]
            agg["cache_read"] += m["cache_read"]
            agg["cache_create"] += m["cache_create"]

        if novel_for_this_file == 0:
            report.sessions_skipped += 1

    entries: list[dict] = []
    for (session_id, model), agg in aggregated.items():
        cost = calculate_cost(
            model,
            {
                "input": agg["input"],
                "output": agg["output"],
                "cache_read": agg["cache_read"],
                "cache_create": agg["cache_create"],
            },
            pricing,
        )
        entries.append(
            {
                "session": session_id,
                "date": agg["date"],
                "model": model,
                "profile": profile.name,
                "project": agg["project"],
                "input": agg["input"],
                "output": agg["output"],
                "cache_read": agg["cache_read"],
                "cache_create": agg["cache_create"],
                "cost": cost,
            }
        )

    db.replace_profile_stats(profile.name, entries)
    report.sessions_updated = len({e["session"] for e in entries})
    return report


def ingest_all(
    cfg: Config,
    db: MetricsDB,
    pricing: dict[str, dict[str, float]],
) -> IngestReport:
    total = IngestReport()
    for prof in list_profiles(cfg):
        config_path = expand_path(str(prof.config_dir))
        resolved = ProfileInfo(
            name=prof.name,
            config_dir=config_path,
            roots=prof.roots,
            is_default=prof.is_default,
            exists=config_path.is_dir(),
        )
        if not resolved.exists:
            continue
        total.merge(ingest_profile(resolved, db, pricing))
    return total
