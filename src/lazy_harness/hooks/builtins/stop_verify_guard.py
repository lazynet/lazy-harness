"""Stop hook: soft-enforce verification before a session with a declared goal closes.

See specs/designs/2026-08-16-loop-engineering-design.md, "Soft enforcement on
`Stop`". Once per session: if the session declared a goal (native `/goal
<condition>`) and no `verify_ran` event exists for it, the first Stop attempt
blocks with a reminder; the second closes regardless. The event is recorded
either way. Gated behind `[loops] inject_goal_prompt`, the same flag its
sibling `user_prompt_goal.py` uses — when it is off this hook does nothing.

Fail-soft: every path abstains. A hook that raises takes down the chain.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.agents.base import (
    HookDecision,
    HookEvent,
    Signal,
    TranscriptReader,
    Verdict,
)

_BLOCK_REASON = (
    "Esta sesión declaró un goal (/goal) y todavía no hay evidencia de que "
    "corriste la verificación (skill verify-before-done) antes de cerrar. "
    "Verificá antes de terminar — este aviso no se repite en esta sesión."
)


def _goal_declared(transcript_path: Path, reader: TranscriptReader | None) -> bool:
    """True if the transcript carries an explicit, user-set goal.

    This is the hook's half of decision 11: `stop-verify-guard` *declares*
    `Signal.GOAL_STATUS` in the builtin registry, and here it consumes exactly
    that — the declaration and the read are the same word. What the marker
    looks like on disk is the reader's business, so the guard no longer knows
    that Claude Code writes an `attachment` whose `type` is `"goal_status"`.

    `reader is None` is "this agent's transcript cannot be read at all", and it
    reports no goal, which is the only thing the guard can do at runtime: the
    deploy-time answer — refusing to install a hook whose signals an agent does
    not supply — is step 4's, not this function's.

    A reader that delivers messages and tokens but no `GOAL_STATUS` lands in
    the same place by a different route, and that is the whole point of naming
    signals rather than carrying a `requires_transcript` boolean: such a reader
    must not silently re-enable a guard that would then always pass.

    This stays a different, narrower signal than the compound-loop worker's
    `goal_declared`/`goal_absent` verdict: that one judges prose success
    criteria via an LLM classification made *after* the session ends, and is
    structurally unavailable at `Stop` time.
    """
    if reader is None:
        return False
    # `any` over the iterator rather than a list: the read stops at the first
    # marker instead of parsing a transcript that can run to hundreds of
    # megabytes by the time a Stop hook sees it.
    return any(event.signal is Signal.GOAL_STATUS for event in reader.read(transcript_path))


def _db_path() -> Path:
    from lazy_harness.monitoring.db import resolve_db_path

    return resolve_db_path()


def _injection_enabled() -> bool:
    try:
        from lazy_harness.core.config import load_config
        from lazy_harness.core.paths import config_file

        return bool(load_config(config_file()).loops.inject_goal_prompt)
    except Exception:
        return False


def main(event: HookEvent) -> HookDecision:
    """Block the first Stop of a session that declared a goal and never verified.

    `Verdict.BLOCK` rather than `DENY`: on a stop-class event the agent is
    asked to keep working, not refused a tool call, and the adapter is what
    knows those serialise differently.
    """
    try:
        if not _injection_enabled():
            return HookDecision()

        if not event.session_id:
            return HookDecision()

        from lazy_harness.hooks.builtins._shared import project_key, transcript_reader

        transcript_path = event.transcript_path
        if transcript_path is None or not transcript_path.is_file():
            return HookDecision()
        # Resolved per invocation rather than held: `HookEvent.profile` is what
        # says whose agent — and so whose transcript format — this session runs.
        if not _goal_declared(transcript_path, transcript_reader(event.profile)):
            return HookDecision()

        # A payload with no `cwd` parses as `Path(".")`, and a project key
        # derived from that would label the metric with whatever directory the
        # agent happened to spawn the hook from rather than with the project.
        project = project_key(event.cwd) if event.cwd != Path(".") else ""

        from lazy_harness.monitoring.db import MetricsDB

        db = MetricsDB(_db_path())

        if db.has_loop_event(event.session_id, "verify_ran"):
            return HookDecision()

        if db.has_loop_event(event.session_id, "verify_block"):
            db.record_loop_event(
                session=event.session_id,
                kind="verify_skipped",
                project=project,
                profile=event.profile,
            )
            return HookDecision()

        db.record_loop_event(
            session=event.session_id,
            kind="verify_block",
            project=project,
            profile=event.profile,
        )
    except Exception:
        # A hook must degrade, never crash the chain: any failure here (bad
        # payload shape, an unreadable transcript, an unwritable metrics
        # store) is swallowed so the session continues uninterrupted.
        return HookDecision()
    return HookDecision(verdict=Verdict.BLOCK, reason=_BLOCK_REASON)
