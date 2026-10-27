"""Last-run queries use scheduler evidence before log timestamps."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from lazy_harness.scheduler.cron import CronBackend
from lazy_harness.scheduler.launchd import LaunchdBackend
from lazy_harness.scheduler.systemd import SystemdBackend


def test_systemd_last_run_parses_systemd_257_probe(tmp_path: Path) -> None:
    calls = []

    def runner(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="LastTriggerUSec=Mon 2026-10-26 23:30:13 UTC\n"
            "LastTriggerUSecMonotonic=2d 17h 51min 39.584059s\n",
        )

    backend = SystemdBackend(unit_dir=tmp_path, runner=runner)
    assert backend.last_run("lazy-harness-metrics-ingest") == datetime(
        2026, 10, 26, 23, 30, 13, tzinfo=UTC
    )
    assert calls == [
        [
            "systemctl",
            "--user",
            "show",
            "lazy-harness-metrics-ingest.timer",
            "-p",
            "LastTriggerUSec",
        ]
    ]


@pytest.mark.parametrize(
    "output",
    [
        "LastTriggerUSec=\nLastTriggerUSecMonotonic=0\n",
        "LastTriggerUSec=n/a\n",
        "LastTriggerUSec=0\n",
        "LastTriggerUSec=invalid\n",
        "",
    ],
)
def test_systemd_last_run_without_a_timestamp(output: str) -> None:
    backend = SystemdBackend(runner=lambda argv: subprocess.CompletedProcess(argv, 0, output))
    assert backend.last_run("lazy-harness-x") is None


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(),
        SimpleNamespace(returncode=0),
        SimpleNamespace(stdout="LastTriggerUSec=Mon 2026-10-26 23:30:13 UTC\n"),
        subprocess.CompletedProcess([], 1, "LastTriggerUSec=Mon 2026-10-26 23:30:13 UTC\n"),
    ],
)
def test_systemd_last_run_requires_success_and_output(result: object) -> None:
    assert SystemdBackend(runner=lambda argv: result).last_run("lazy-harness-x") is None


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("systemctl", 10)])
def test_systemd_last_run_unavailable(error: Exception) -> None:
    def runner(argv):
        raise error

    assert SystemdBackend(runner=runner).last_run("lazy-harness-x") is None


@pytest.mark.parametrize(
    "backend,label", [(LaunchdBackend(), "com.lazy-harness.x"), (CronBackend(), "lazy-harness-x")]
)
@pytest.mark.parametrize("stamped", [True, False])
def test_log_backends_keep_timestamp_and_mtime_fallback(
    tmp_path: Path, monkeypatch, backend, label: str, stamped: bool
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log = tmp_path / ".local/share/lazy-harness/logs/x-stdout.log"
    log.parent.mkdir(parents=True)
    log.write_text("[2026-10-26 12:00:00] done\n" if stamped else "done\n")
    expected = (
        datetime(2026, 10, 26, 12) if stamped else datetime.fromtimestamp(log.stat().st_mtime)
    )
    assert backend.last_run(label) == expected


@pytest.mark.parametrize(
    "backend,label", [(LaunchdBackend(), "com.lazy-harness.x"), (CronBackend(), "lazy-harness-x")]
)
def test_log_backends_without_logs(tmp_path: Path, monkeypatch, backend, label: str) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert backend.last_run(label) is None


def test_systemd_probe_uses_a_stable_locale_and_timezone(monkeypatch) -> None:
    from lazy_harness.scheduler.systemd import _default_runner

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: calls.append(kw))
    _default_runner(["systemctl", "--user", "show", "x.timer"])
    assert calls[0]["env"]["LC_ALL"] == "C"
    assert calls[0]["env"]["TZ"] == "UTC"
