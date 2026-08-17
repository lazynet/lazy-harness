"""Tests for `lh status queue`."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import Config, HarnessConfig
from lazy_harness.core.profiles import ProfileInfo
from lazy_harness.monitoring.views import queue as queue_view
from lazy_harness.monitoring.views._helpers import StatusContext

from ._render import render_to_text


def _ctx(config_dir: Path, name: str = "lazy") -> StatusContext:
    return StatusContext(
        cfg=Config(harness=HarnessConfig(version="1")),
        profiles=[
            ProfileInfo(
                name=name, config_dir=config_dir, roots=[], is_default=True, exists=True
            )
        ],
    )


def test_queue_counts_pending_and_done(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    (queue_dir / "done").mkdir(parents=True)
    (queue_dir / "a.task").write_text("")
    (queue_dir / "b.task").write_text("")
    (queue_dir / "done" / "c.task").write_text("")

    text = render_to_text(queue_view.render(_ctx(tmp_path)))

    assert "lazy" in text
    assert "Pending:    2" in text
    assert "Done total: 1" in text


def test_queue_skips_a_profile_that_does_not_exist(tmp_path: Path) -> None:
    ctx = StatusContext(
        cfg=Config(harness=HarnessConfig(version="1")),
        profiles=[
            ProfileInfo(
                name="ghost", config_dir=tmp_path, roots=[], is_default=True, exists=False
            )
        ],
    )

    assert "ghost" not in render_to_text(queue_view.render(ctx))


def test_queue_lists_recent_worker_activity(tmp_path: Path) -> None:
    (tmp_path / "queue").mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "compound-loop.log").write_text(
        "2026-08-17T10:00:00 wrote a decision\n2026-08-17T10:01:00 error while draining\n"
    )

    text = render_to_text(queue_view.render(_ctx(tmp_path)))

    assert "Recent worker activity" in text
    assert "wrote a decision" in text
    assert "✗" in text, "an error line must carry the failure marker"
