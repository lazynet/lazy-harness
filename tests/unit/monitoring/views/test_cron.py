"""Tests for `lh status cron`."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.monitoring.views import cron as cron_view
from lazy_harness.scheduler.base import JobRecord, JobState

from ._fixtures import ctx
from ._render import render_to_text


class _Backend:
    def __init__(self, records: list[JobRecord]) -> None:
        self._records = records

    def discover(self) -> list[JobRecord]:
        return self._records


def test_cron_says_so_when_no_jobs_are_managed(tmp_path: Path) -> None:
    text = render_to_text(cron_view.render(ctx(tmp_path, scheduler_backend=_Backend([]))))
    assert "No managed jobs" in text


def test_cron_reports_an_unknown_state_with_its_reason(tmp_path: Path) -> None:
    """A backend that cannot check must not be rendered as a failure — that is
    what made `lh status cron` show every job as ✗ on any host without
    launchctl."""
    backend = _Backend(
        [
            JobRecord(
                name="qmd-sync",
                label="x.qmd-sync",
                schedule="0 6 * * *",
                state=JobState.UNKNOWN,
                detail="launchctl unavailable",
            )
        ]
    )

    text = render_to_text(cron_view.render(ctx(tmp_path, scheduler_backend=backend)))

    assert "qmd-sync" in text
    assert "launchctl unavailable" in text
    assert "✗" not in text


def test_cron_renders_a_loaded_job(tmp_path: Path) -> None:
    backend = _Backend(
        [JobRecord(name="embed", label="x.embed", schedule="0 6 * * *", state=JobState.LOADED)]
    )

    text = render_to_text(cron_view.render(ctx(tmp_path, scheduler_backend=backend)))

    assert "embed" in text
    assert "0 6 * * *" in text


def test_cron_survives_a_context_with_no_backend(tmp_path: Path) -> None:
    """`scheduler_backend` is Optional on the context, so the view must not
    assume it was resolved."""
    assert "No managed jobs" in render_to_text(cron_view.render(ctx(tmp_path)))
