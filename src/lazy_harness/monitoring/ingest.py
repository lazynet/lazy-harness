"""Metrics ingest pipeline.

Walks each profile's `<config_dir>/projects/**/*.jsonl`, parses token usage,
prices it, and UPSERTs into the metrics DB. Uses file mtime to skip
sessions that haven't changed since the previous run. Re-ingesting is
idempotent: totals are computed from the full (append-only) JSONL and
overwrite prior rows keyed by `(session, model)`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lazy_harness.core.config import Config
from lazy_harness.core.paths import expand_path
from lazy_harness.core.profiles import ProfileInfo, list_profiles
from lazy_harness.monitoring.collector import extract_project_name, parse_session
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.pricing import calculate_cost


@dataclass
class IngestReport:
    sessions_scanned: int = 0
    sessions_updated: int = 0
    sessions_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: IngestReport) -> None:
        self.sessions_scanned += other.sessions_scanned
        self.sessions_updated += other.sessions_updated
        self.sessions_skipped += other.sessions_skipped
        self.errors.extend(other.errors)


def ingest_profile(
    profile: ProfileInfo,
    db: MetricsDB,
    pricing: dict[str, dict[str, float]],
) -> IngestReport:
    report = IngestReport()
    projects_dir = profile.config_dir / "projects"
    if not projects_dir.is_dir():
        return report

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = extract_project_name(project_dir.name)
        for session_file in sorted(project_dir.glob("*.jsonl")):
            report.sessions_scanned += 1
            try:
                mtime_ns = session_file.stat().st_mtime_ns
            except OSError as e:
                report.errors.append(f"{session_file}: {e}")
                continue

            session_id = session_file.stem
            last_mtime = db.get_ingest_mtime(session_id)
            if last_mtime is not None and last_mtime == mtime_ns:
                report.sessions_skipped += 1
                continue

            try:
                parsed = parse_session(session_file)
            except Exception as e:  # pragma: no cover - defensive
                report.errors.append(f"{session_file}: {e}")
                continue

            if not parsed:
                db.set_ingest_mtime(session_id, mtime_ns)
                continue

            entries = []
            for p in parsed:
                cost = calculate_cost(
                    p["model"],
                    {
                        "input": p["input"],
                        "output": p["output"],
                        "cache_read": p["cache_read"],
                        "cache_create": p["cache_create"],
                    },
                    pricing,
                )
                entries.append(
                    {
                        "session": p["session"],
                        "date": p["date"],
                        "model": p["model"],
                        "profile": profile.name,
                        "project": project_name,
                        "input": p["input"],
                        "output": p["output"],
                        "cache_read": p["cache_read"],
                        "cache_create": p["cache_create"],
                        "cost": cost,
                    }
                )
            db.upsert_stats(entries)
            db.set_ingest_mtime(session_id, mtime_ns)
            report.sessions_updated += 1

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
