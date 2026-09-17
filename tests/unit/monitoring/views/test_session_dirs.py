"""`lh status` asks each profile's agent where its artefacts live.

Six view call sites used to hardcode `p.config_dir / "projects"` and one
`/ "logs"`, so a Codex or Copilot profile rendered as having zero projects and
zero sessions — indistinguishable from a profile that had done no work.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import Config, HarnessConfig, ProfileEntry
from lazy_harness.core.profiles import ProfileInfo
from lazy_harness.monitoring.views._helpers import StatusContext


def _ctx(tmp_path: Path, agent: str) -> tuple[StatusContext, ProfileInfo]:
    cfg = Config(harness=HarnessConfig(version="1"))
    cfg.profiles.items = {"p": ProfileEntry(config_dir=str(tmp_path), agent=agent)}
    prof = ProfileInfo(name="p", config_dir=tmp_path, roots=[], is_default=True, exists=True)
    return StatusContext(cfg=cfg, profiles=[prof]), prof


def test_sessions_dir_is_projects_for_claude_code(tmp_path: Path) -> None:
    ctx, prof = _ctx(tmp_path, "claude-code")
    assert ctx.sessions_dir(prof) == tmp_path / "projects"


def test_sessions_dir_is_sessions_for_codex(tmp_path: Path) -> None:
    """The literal is gone: nothing here knows the name `projects`."""
    ctx, prof = _ctx(tmp_path, "codex")
    assert ctx.sessions_dir(prof) == tmp_path / "sessions"


def test_sessions_dir_refuses_for_an_agent_that_declares_none(tmp_path: Path) -> None:
    """`null` is the shipped sentinel, and `Path(x) / ""` would return `tmp_path`."""
    ctx, prof = _ctx(tmp_path, "null")
    assert ctx.sessions_dir(prof) is None


def test_logs_dir_refuses_for_an_agent_that_declares_none(tmp_path: Path) -> None:
    ctx, prof = _ctx(tmp_path, "codex")
    assert ctx.logs_dir(prof) is None


def test_queue_dir_refuses_for_an_agent_that_declares_none(tmp_path: Path) -> None:
    ctx, prof = _ctx(tmp_path, "codex")
    assert ctx.queue_dir(prof) is None


def test_logs_dir_is_the_declared_one_for_claude_code(tmp_path: Path) -> None:
    ctx, prof = _ctx(tmp_path, "claude-code")
    assert ctx.logs_dir(prof) == tmp_path / "logs"
    assert ctx.queue_dir(prof) == tmp_path / "queue"


def test_the_projects_view_counts_a_codex_profiles_own_sessions(tmp_path: Path) -> None:
    """End to end through a view: the count came out zero before this change."""
    from lazy_harness.monitoring.views.projects import render as render_projects

    ctx, _prof = _ctx(tmp_path, "codex")
    d = tmp_path / "sessions" / "2026"
    d.mkdir(parents=True)
    (d / "rollout-2026-09-16T09-02-04-abc.jsonl").write_text("{}\n")

    from tests.unit.monitoring.views._render import render_to_text

    assert "2026" in render_to_text(render_projects(ctx))


def test_the_overview_counts_a_codex_profiles_own_projects(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views.overview import render as render_overview

    ctx, _prof = _ctx(tmp_path, "codex")
    (tmp_path / "sessions" / "2026").mkdir(parents=True)

    from tests.unit.monitoring.views._render import render_to_text

    assert "p: 1" in render_to_text(render_overview(ctx, None))
