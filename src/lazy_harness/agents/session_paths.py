"""Where an agent keeps its session artefacts, and what that implies.

One importable answer to a question fourteen call sites used to answer each in
its own spelling. Three of them wrote
`agent.session_dirs().get("sessions") or "projects"`, one wrote
`or "logs"`, and six skipped the adapter entirely with a bare
`profile.config_dir / "projects"` — so a profile running any agent but Claude
Code was walked as though it were one.

**The fallback is not a safe default, it is a wrong answer that cannot be
seen.** `Path(x) / ""` evaluates to `x` itself, so the obvious spelling of "no
subdirectory declared" hands the caller the whole config directory: probing it
for transcripts finds `settings.json` and reports every agent without a
sessions directory as having unread data. `session_path` returns `None` instead,
which a caller cannot accidentally treat as a directory.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from lazy_harness.agents.base import TranscriptReader


def session_subdir(agent: Any, key: str) -> str:
    """The subdirectory `agent` declares for `key`, or `""` for none.

    `getattr` rather than `agent.session_dirs()`: every caller here takes its
    adapter by injection, and an object missing the attribute must degrade to
    "declares nothing" rather than raise out of a diagnostic. The same guard
    covers an adapter answering with something that is not a `dict[str, str]`.
    """
    declare = getattr(agent, "session_dirs", None)
    if not callable(declare):
        return ""
    declared = declare()
    if not isinstance(declared, dict):
        return ""
    value = declared.get(key)
    return value if isinstance(value, str) else ""


def session_path(agent: Any, config_dir: Path, key: str) -> Path | None:
    """`config_dir / <declared subdir>`, or `None` when the agent declares none.

    `None` and never `config_dir`: see the module docstring for why the
    difference is invisible at the call site if this returns a path.
    """
    subdir = session_subdir(agent, key)
    return config_dir / subdir if subdir else None


class TranscriptHealth(StrEnum):
    """What `lh doctor` can *derive* about a profile's transcripts.

    Derived, never declared. "Should this agent have a reader?" has no
    configured answer and does not need one: the question that matters is
    whether data is going unread, and `TranscriptReader` being
    `runtime_checkable` makes `isinstance` the whole test. A per-agent
    expectation in a registry would be a hand-maintained list beside the code,
    and would require an adapter that *should* have a reader to declare its own
    defect.

    The consequence is that a Claude Code profile whose reader regressed and a
    Copilot profile that never had one both derive `DEGRADED`. That is not a
    lost distinction — it is the same fact ("transcripts exist and nothing
    reads them"), and which of the two it is belongs to whoever reads the line,
    not to a table someone has to remember to update.
    """

    OK = "ok"
    """A reader, and transcripts for it to read."""

    DEGRADED = "degraded"
    """Transcripts exist and no reader can open them."""

    NO_DATA = "no_data"
    """A location is declared; nothing matching a transcript is there.

    Covers a directory that does not exist, which is a *declared* location that
    is simply wrong — Copilot 1.0.83 has been referred to as writing
    `history-session-state/`, and does not. `NO_LOCATION` would say the agent
    never answered, which is a different failure and a different fix.
    """

    NO_LOCATION = "no_location"
    """The agent declares no sessions directory at all."""


def transcript_health(agent: Any, config_dir: Path) -> TranscriptHealth:
    """Read nothing, decide from what is declared and what is on disk.

    The absence of a location is answered **first**, and it has to be: the
    ordering is what keeps the `Path(x) / ""` trap out of the answer.

    Matching `*.jsonl` rather than any directory entry is the second half of
    the same fix — Codex keeps a `session-store.db` beside its rollouts, and a
    check for "anything at all" calls that unread transcript data.
    """
    sessions = session_path(agent, config_dir, "sessions")
    if sessions is None:
        return TranscriptHealth.NO_LOCATION
    try:
        has_data = sessions.is_dir() and any(sessions.rglob("*.jsonl"))
    except OSError:
        # An unreadable directory is not a declaration; report what we could
        # not see as absent data rather than raising out of a health check.
        has_data = False
    if not has_data:
        return TranscriptHealth.NO_DATA
    return TranscriptHealth.OK if isinstance(agent, TranscriptReader) else TranscriptHealth.DEGRADED
