"""Tests for `lh status cron`."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

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


def test_cron_journal_only_job_uses_scheduler_time(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    from lazy_harness.scheduler.systemd import SystemdBackend

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    units = tmp_path / "units"
    units.mkdir()
    (units / "lazy-harness-metrics-ingest.timer").write_text("[Timer]\nOnCalendar=hourly\n")
    backend = SystemdBackend(
        unit_dir=units,
        runner=lambda argv: subprocess.CompletedProcess(
            argv,
            0,
            "active\n" if "is-active" in argv else "LastTriggerUSec=Mon 2026-10-26 23:30:13 UTC\n",
        ),
    )
    seen = []
    monkeypatch.setattr(cron_view, "time_ago", lambda ts: seen.append(ts) or "11m ago")
    text = render_to_text(cron_view.render(ctx(tmp_path, scheduler_backend=backend)))
    assert "metrics-ingest" in text
    assert "11m ago" in text
    assert seen == [
        datetime(2026, 10, 26, 23, 30, 13, tzinfo=UTC).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
    ]


@pytest.mark.parametrize("has_query", [True, False])
def test_cron_falls_back_when_query_is_absent_or_unknown(
    tmp_path: Path, monkeypatch, has_query: bool
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    backend = _Backend([JobRecord("x", "custom.x", "hourly", JobState.LOADED)])
    if has_query:
        backend.last_run = lambda label: None
    logs = tmp_path / ".local/share/lazy-harness/logs"
    logs.mkdir(parents=True)
    (logs / "x.log").write_text("[2026-10-26 12:00:00] done\n")
    monkeypatch.setattr(
        cron_view, "time_ago", lambda ts: "log fallback" if ts == "2026-10-26T12:00:00" else "wrong"
    )
    assert "log fallback" in render_to_text(
        cron_view.render(ctx(tmp_path, scheduler_backend=backend))
    )
