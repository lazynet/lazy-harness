"""Metrics ingest pipeline.

Reads every profile's transcripts **through its own agent's reader** — never a
literal `projects/` and never a hand-written parser for one dialect — and
upserts one `session_stats` row per `(session, model)` on every run.

The agent answers three questions this module used to answer for it: where the
transcripts are (`locate_sessions`), what a line means (`read`), and which
session and project a transcript belongs to (`session_identity`). What is left
here is the metering itself, plus the one exclusion that is genuinely this
harness's own business rather than the agent's — see `memory/` below.

A profile whose agent declares no sessions directory, or **implements no
`TranscriptReader`**, is skipped rather than walked as though it were Claude
Code. Walking it would find nothing and report the profile empty, which is
indistinguishable from a profile that did no work; `lh doctor`'s transcript
line carries the verdict instead. ADR-053 made that test a capability where
ADR-051 had made it a name, so an agent that can be read is metered whatever
it is called.

Two precision properties the pipeline guarantees:

1. **Cross-file message-id dedup** — Claude Code's `/resume` writes a new
   JSONL that re-includes the prior conversation. Without dedup, the shared
   prefix gets double-counted. `TranscriptEvent.message_id` carries the
   provider's own id for the turn (Claude Code's `message.id`, Codex's
   `response_id`); we attribute it to the oldest file (by mtime) that mentions
   it and ignore every subsequent occurrence. An event whose provider offers
   no such id is counted every time it is seen — there is nothing to match on,
   and dropping it would be worse than counting it twice.

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

from lazy_harness.agents.base import (
    SessionIdentity,
    Signal,
    TranscriptIdentity,
    TranscriptReader,
)
from lazy_harness.agents.session_paths import session_path
from lazy_harness.core.config import Config
from lazy_harness.core.identity import resolve_host, resolve_identity
from lazy_harness.core.paths import expand_path
from lazy_harness.core.profiles import ProfileInfo, list_profiles
from lazy_harness.monitoring.collector import extract_session_date
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.event_id import derive_event_id
from lazy_harness.monitoring.pricing import cost_for_billing_model
from lazy_harness.plugins.contracts import (
    METRIC_EVENT_SCHEMA_VERSION,
    MetricEvent,
)

# Directory name, anywhere under the sessions tree, whose `*.jsonl` are this
# harness's own episodic logs rather than agent transcripts — 17 of them on the
# measured host. The readers yield them because they *are* JSONL under the
# tree, and correctly so: what this directory holds is a statement about what
# `lazy-harness` writes under an agent's config dir, not about the agent. It is
# the one dimension of ADR-051's measured gap that ADR-053 deliberately left
# with the consumer.
_HARNESS_LOG_DIR = "memory"


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
    agent: TranscriptReader,
    config_dir: Path,
    errors: list[str],
) -> list[Path]:
    """Every transcript this run will meter, oldest write first.

    The walk itself belongs to the agent — `locate_sessions` knows the tree's
    shape and its file naming, and neither is the same for two agents. Two
    things are decided here instead.

    **Order.** `locate_sessions` promises none; dedup needs one. A message id
    is attributed to the oldest file that mentions it, so the sort is what
    makes "which file owns this turn" a stable answer across runs rather than
    whatever order the filesystem returned.

    **The `memory/` exclusion.** Skipped at any depth, and skipped here rather
    than in the reader, because it is a fact about what this harness writes
    under an agent's config directory — a reader that learned to hide those
    files would be answering a question that is not its own, and would hide
    them from every other consumer too.
    """
    stamped: list[tuple[int, Path]] = []
    for path in agent.locate_sessions(config_dir, None):
        if _HARNESS_LOG_DIR in path.parts[:-1]:
            continue
        try:
            stamped.append((path.stat().st_mtime_ns, path))
        except OSError as e:
            errors.append(f"{path}: {e}")
            continue
    stamped.sort(key=lambda t: t[0])
    return [path for _mtime_ns, path in stamped]


def _identify(agent: object, path: Path) -> SessionIdentity:
    """Which session and project a transcript bills to.

    An agent that cannot say falls back to the file's own stem and no project,
    which is what every consumer did before `TranscriptIdentity` existed. A
    reader is not required to implement it — that is the whole reason it is a
    second Protocol — so this is a degradation, not a refusal.
    """
    if isinstance(agent, TranscriptIdentity):
        return agent.session_identity(path)
    return SessionIdentity(session_id=path.stem)


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

        agent = get_agent("claude-code")
    # Both refusals are silent here and named by `lh doctor`: an ingest run
    # prints per-profile errors, and a profile it was never going to read is
    # not an error of this run. The first is a *capability* test and not a
    # name — ADR-053. `TranscriptReader` is runtime_checkable, so this is the
    # whole check and it tracks the code rather than a list.
    agent_name = getattr(agent, "name", "")
    if not isinstance(agent, TranscriptReader):
        return report
    sessions_dir = session_path(agent, profile.config_dir, "sessions")
    if sessions_dir is None or not sessions_dir.is_dir():
        return report

    files = _find_session_files(agent, profile.config_dir, report.errors)

    seen_msg_ids: set[str] = set()
    aggregated: dict[tuple[str, str], dict] = {}

    for session_file in files:
        report.sessions_scanned += 1
        identity = _identify(agent, session_file)
        session_date = extract_session_date(session_file)
        novel_for_this_file = 0
        for event in agent.read(session_file):
            if event.signal is not Signal.TOKEN_USAGE or event.usage is None:
                continue
            report.messages_total += 1
            # A provider with no stable id for the turn gets counted every
            # time: there is nothing to match on, and dropping an unidentified
            # turn loses real tokens where double-counting one only inflates a
            # resume's shared prefix.
            if event.message_id is not None:
                if event.message_id in seen_msg_ids:
                    report.messages_deduped += 1
                    continue
                seen_msg_ids.add(event.message_id)
            novel_for_this_file += 1
            # `UNIQUE(session, model)` needs a model, and an event that names
            # none still spent tokens. "unknown" is the spelling the pricing
            # table already treats as unpriced, which is the honest outcome.
            key = (identity.session_id, event.model or "unknown")
            agg = aggregated.get(key)
            if agg is None:
                agg = {
                    "input": 0,
                    "output": 0,
                    "cache_read": 0,
                    "cache_create": 0,
                    "cache_create_1h": 0,
                    "date": session_date,
                    "project": identity.project or "",
                }
                aggregated[key] = agg
            usage = event.usage
            agg["input"] += usage.input_tokens or 0
            agg["output"] += usage.output_tokens or 0
            agg["cache_read"] += usage.cache_read_tokens or 0
            agg["cache_create"] += usage.cache_creation_tokens or 0
            agg["cache_create_1h"] += usage.cache_creation_1h_tokens or 0
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
