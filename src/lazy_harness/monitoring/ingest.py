"""Metrics ingest pipeline.

Walks the sessions tree **the profile's own agent declares** — never a literal
`projects/` — parses token usage from every session JSONL (including nested
subagent files), and upserts one `session_stats` row per `(session, model)` on
every run.

A profile whose agent declares no sessions directory, or whose transcripts are
in a dialect this parser was not written for, is **skipped** rather than walked
as though it were Claude Code. Walking it would find nothing and report the
profile empty, which is indistinguishable from a profile that did no work;
`lh doctor`'s transcript line carries the verdict instead.

Two precision properties the pipeline guarantees:

1. **Cross-file message-id dedup** — Claude Code's `/resume` writes a new
   JSONL that re-includes the prior conversation. Without dedup, the shared
   prefix gets double-counted. Every assistant message has a stable
   `message.id`; we attribute it to the oldest file (by mtime) that mentions
   it and ignore every subsequent occurrence.

2. **Overwrite, never accumulate** — `upsert_stats` writes each row with
   `ON CONFLICT(session, model) DO UPDATE`, so re-reading a transcript that
   grew since the last run stores the new total rather than adding to the
   old one.

What this is NOT is a rebuild. Nothing here deletes, and a run is not one
transaction: a session absent from this walk keeps its last-written row.
That is deliberate — Claude Code prunes transcripts on `cleanupPeriodDays`
and cost history must not shrink to a rolling window with them
(`test_ingest_preserves_sessions_after_transcript_pruned`). The cost is that
`session_stats` outgrows what is on disk, and that a row whose transcript is
gone can never be re-derived, so it can never reach a sink that was
configured after it was last written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lazy_harness.agents.session_paths import session_path
from lazy_harness.core.config import Config
from lazy_harness.core.identity import resolve_host, resolve_identity
from lazy_harness.core.paths import expand_path
from lazy_harness.core.profiles import ProfileInfo, list_profiles
from lazy_harness.monitoring.collector import (
    extract_project_name,
    extract_session_date,
    iter_assistant_messages,
)
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.event_id import derive_event_id
from lazy_harness.monitoring.pricing import cost_for_billing_model
from lazy_harness.plugins.contracts import (
    METRIC_EVENT_SCHEMA_VERSION,
    MetricEvent,
)

# The registry key of the agent whose transcript dialect `iter_assistant_messages`
# parses. A name, and not a capability query, because nothing in `AgentAdapter`
# answers "what dialect is your transcript" — `TranscriptReader` says a reader
# exists, not that its events carry what metering needs. ADR-051 measures the
# gap and proposes the fields that would delete this constant.
_PARSED_DIALECT = "claude-code"


@dataclass
class IngestReport:
    sessions_scanned: int = 0
    sessions_updated: int = 0
    sessions_skipped: int = 0
    messages_total: int = 0
    messages_deduped: int = 0
    errors: list[str] = field(default_factory=list)
    unknown_models: set[str] = field(default_factory=set)

    def merge(self, other: IngestReport) -> None:
        self.sessions_scanned += other.sessions_scanned
        self.sessions_updated += other.sessions_updated
        self.sessions_skipped += other.sessions_skipped
        self.messages_total += other.messages_total
        self.messages_deduped += other.messages_deduped
        self.errors.extend(other.errors)
        self.unknown_models |= other.unknown_models


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
    *,
    agent: Any | None = None,
    sinks: list[Any] | None = None,
    user_id: str = "local",
    tenant_id: str = "local",
    host: str = "",
    workload_by_session: dict[str, str] | None = None,
    billing_model: str = "per_token",
) -> IngestReport:
    report = IngestReport()
    if agent is None:
        from lazy_harness.agents.registry import get_agent

        agent = get_agent(_PARSED_DIALECT)
    # Both refusals are silent here and named by `lh doctor`: an ingest run
    # prints per-profile errors, and a profile it was never going to read is
    # not an error of this run.
    agent_name = getattr(agent, "name", "")
    if agent_name != _PARSED_DIALECT:
        return report
    sessions_dir = session_path(agent, profile.config_dir, "sessions")
    if sessions_dir is None or not sessions_dir.is_dir():
        return report

    files = _find_session_files(sessions_dir, report.errors)

    seen_msg_ids: set[str] = set()
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
                    "cache_create_1h": 0,
                    "date": session_date,
                    "project": project_name,
                }
                aggregated[key] = agg
            agg["input"] += m["input"]
            agg["output"] += m["output"]
            agg["cache_read"] += m["cache_read"]
            agg["cache_create"] += m["cache_create"]
            agg["cache_create_1h"] += m["cache_create_1h"]
        if novel_for_this_file == 0:
            report.sessions_skipped += 1

    entries: list[dict] = []
    events: list[MetricEvent] = []
    for (session_id, model), agg in aggregated.items():
        cost, cost_source = cost_for_billing_model(
            model,
            {
                "input": agg["input"],
                "output": agg["output"],
                "cache_read": agg["cache_read"],
                "cache_create": agg["cache_create"],
                "cache_create_1h": agg["cache_create_1h"],
            },
            pricing,
            billing_model=billing_model,
            on=agg["date"],
        )
        # cost_source is None for exactly the gap this report exists to
        # surface: a per_token row whose model has no rate. A flat_rate row
        # never reaches this branch — its usage is real but not per-token
        # metered, so an unpriced model is not a pricing gap.
        if cost_source is None:
            report.unknown_models.add(model)
        # The TTL split only has to survive as far as the price. Stored rows
        # and the sink payload keep one cache-write token total: splitting
        # the column would cost a schema migration and a wire-format bump
        # for a distinction no reader consumes.
        cache_create_total = agg["cache_create"] + agg["cache_create_1h"]
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
                "cache_create": cache_create_total,
                "cost": cost,
                "agent": agent_name,
                "billing_model": billing_model,
            }
        )
        events.append(
            MetricEvent(
                event_id=derive_event_id(profile=profile.name, session=session_id, model=model),
                schema_version=METRIC_EVENT_SCHEMA_VERSION,
                user_id=user_id,
                tenant_id=tenant_id,
                profile=profile.name,
                session=session_id,
                model=model,
                project=agg["project"],
                date=agg["date"],
                input_tokens=agg["input"],
                output_tokens=agg["output"],
                cache_read=agg["cache_read"],
                cache_create=cache_create_total,
                cost=cost,
                host=host,
                # Recorded by `lh exec` against the session id it pinned before
                # spawning. A session nobody labelled joins nothing and stays
                # empty, which is the right answer for interactive work.
                workload=(workload_by_session or {}).get(session_id, ""),
                agent=agent_name,
                billing_model=billing_model,
                cost_source=cost_source,
            )
        )

    db.upsert_stats(entries)
    report.sessions_updated = len({e["session"] for e in entries})

    if sinks:
        for sink in sinks:
            for event in events:
                result = sink.write(event)
                if not result.success:
                    report.errors.append(
                        f"{type(sink).__name__} write failed for {event.event_id}: {result.error}"
                    )
    return report


def ingest_all(
    cfg: Config,
    db: MetricsDB,
    pricing: dict[str, dict[str, float]],
    *,
    sinks: list[Any] | None = None,
) -> IngestReport:
    from lazy_harness.agents.registry import agent_for_profile

    total = IngestReport()
    identity = resolve_identity(explicit=cfg.metrics.user_id or None)
    # Resolved once: the process that ingests a profile's transcripts is
    # running on the machine that produced them, so `host` needs no channel.
    host = resolve_host()
    workload_by_session = db.attribution_map()
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
        entry = cfg.profiles.items.get(prof.name)
        total.merge(
            ingest_profile(
                resolved,
                db,
                pricing,
                # Per profile, never `cfg.agent.type`: a machine whose profiles
                # run different agents has one profile's transcripts billed
                # under another's dialect if the global key answers for both.
                agent=agent_for_profile(cfg, prof.name),
                sinks=sinks,
                user_id=identity.user_id,
                tenant_id=cfg.metrics.tenant_id,
                host=host,
                workload_by_session=workload_by_session,
                billing_model=entry.billing_model if entry is not None else "per_token",
            )
        )
    return total
