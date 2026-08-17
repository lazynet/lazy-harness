"""Tests for `lh status hooks`."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from lazy_harness.monitoring.views import hooks as hooks_view

from ._fixtures import ctx
from ._render import render_to_text


def test_hooks_marks_a_hook_that_ran_today_as_ok(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    # `last_hook_line` matches on the hook name AND the word "fired"; a line
    # without it is a detail line, not a run.
    today = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    (logs / "hooks.log").write_text(
        f"{today} context-inject: fired cwd=/Users/me/repo\n"
    )

    text = render_to_text(hooks_view.render(ctx(tmp_path)))

    assert "context-inject" in text
    assert "ok" in text
    assert "repo" in text


def test_hooks_reports_log_health_for_a_missing_log(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()

    text = render_to_text(hooks_view.render(ctx(tmp_path)))

    assert "Log health" in text
    assert "not found" in text


def test_hooks_skips_a_profile_that_does_not_exist(tmp_path: Path) -> None:
    text = render_to_text(hooks_view.render(ctx(tmp_path, name="ghost", exists=False)))
    assert "ghost" not in text


def test_hooks_ignores_a_log_line_that_is_not_a_run(tmp_path: Path) -> None:
    """`last_hook_line` requires the word "fired": the hooks log also carries
    detail lines for the same hook, and counting those as runs would report a
    hook as healthy on the strength of its own debug output."""
    logs = tmp_path / "logs"
    logs.mkdir()
    today = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    (logs / "hooks.log").write_text(f"{today} context-inject: injected 9059 chars\n")

    text = render_to_text(hooks_view.render(ctx(tmp_path)))

    assert "context-inject" not in text
