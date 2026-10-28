"""Last exit status per job: a scheduled job that fails every run must be visible."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from lazy_harness.scheduler.cron import CronBackend
from lazy_harness.scheduler.launchd import LaunchdBackend
from lazy_harness.scheduler.systemd import SystemdBackend

LABEL = "com.lazy-harness.knowledge-push"

# Trimmed from `launchctl print gui/501/<label>` on macOS.
_LAUNCHD_TAIL = "\tminimum runtime = 10\n\truns = {runs}\n\t{exit_line}\n\n\tevent triggers = {{\n"


def _launchd(output: str, returncode: int = 0) -> LaunchdBackend:
    return LaunchdBackend(
        runner=lambda argv: subprocess.CompletedProcess(argv, returncode, stdout=output.encode())
    )


@pytest.mark.parametrize(
    "exit_line,expected",
    [
        ("last exit code = 0", 0),
        ("last exit code = 1", 1),
        ("last exit code = 78", 78),
        ("last exit code = (never exited)", None),
    ],
)
def test_launchd_last_exit_parses_launchctl_print(exit_line: str, expected: int | None) -> None:
    out = _LAUNCHD_TAIL.format(runs=66, exit_line=exit_line)
    assert _launchd(out).last_exit(LABEL) == expected


def test_launchd_last_exit_without_the_line_is_unknown() -> None:
    assert _launchd("\tstate = not running\n").last_exit(LABEL) is None


def test_launchd_last_exit_asks_the_gui_domain() -> None:
    calls: list[list[str]] = []

    def runner(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"last exit code = 1\n")

    LaunchdBackend(runner=runner).last_exit(LABEL)
    import os

    assert calls == [["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"]]


@pytest.mark.parametrize(
    "error", [FileNotFoundError(), subprocess.TimeoutExpired("launchctl", 10), RuntimeError("x")]
)
def test_launchd_last_exit_command_failure_is_unknown(error: Exception) -> None:
    def runner(argv):
        raise error

    assert LaunchdBackend(runner=runner).last_exit(LABEL) is None


def test_launchd_last_exit_nonzero_returncode_is_unknown() -> None:
    assert _launchd("last exit code = 1\n", returncode=113).last_exit(LABEL) is None


@pytest.mark.parametrize("result", [SimpleNamespace(), SimpleNamespace(returncode=0)])
def test_launchd_last_exit_requires_output(result: object) -> None:
    assert LaunchdBackend(runner=lambda argv: result).last_exit(LABEL) is None


# Captured from `systemctl --user show <unit>.service -p ExecMainStatus
# -p ExecMainStartTimestamp` on a host running these jobs (LC_ALL=C TZ=UTC).
_SYSTEMD_RAN = "ExecMainStartTimestamp=Wed 2026-10-28 15:45:00 UTC\nExecMainStatus={code}\n"
_SYSTEMD_NEVER = "ExecMainStartTimestamp=\nExecMainStatus=0\n"


def _systemd(output: str, returncode: int = 0) -> SystemdBackend:
    return SystemdBackend(
        runner=lambda argv: subprocess.CompletedProcess(argv, returncode, stdout=output)
    )


@pytest.mark.parametrize("code", [0, 1, 203])
def test_systemd_last_exit_parses_show_output(code: int) -> None:
    assert _systemd(_SYSTEMD_RAN.format(code=code)).last_exit("lazy-harness-x") == code


def test_systemd_last_exit_unit_that_never_ran_is_unknown() -> None:
    assert _systemd(_SYSTEMD_NEVER).last_exit("lazy-harness-x") is None


def test_systemd_last_exit_asks_the_service_unit() -> None:
    calls: list[list[str]] = []

    def runner(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=_SYSTEMD_RAN.format(code=1))

    SystemdBackend(runner=runner).last_exit("lazy-harness-x")
    assert calls == [
        [
            "systemctl",
            "--user",
            "show",
            "lazy-harness-x.service",
            "-p",
            "ExecMainStatus",
            "-p",
            "ExecMainStartTimestamp",
        ]
    ]


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("systemctl", 10)])
def test_systemd_last_exit_command_failure_is_unknown(error: Exception) -> None:
    def runner(argv):
        raise error

    assert SystemdBackend(runner=runner).last_exit("lazy-harness-x") is None


@pytest.mark.parametrize(
    "output", ["ExecMainStatus=abc\nExecMainStartTimestamp=Wed 2026-10-28 15:45:00 UTC\n", ""]
)
def test_systemd_last_exit_garbage_is_unknown(output: str) -> None:
    assert _systemd(output).last_exit("lazy-harness-x") is None


def test_systemd_last_exit_nonzero_returncode_is_unknown() -> None:
    assert _systemd(_SYSTEMD_RAN.format(code=1), returncode=1).last_exit("lazy-harness-x") is None


def test_cron_last_exit_is_unknown(tmp_path: Path) -> None:
    assert CronBackend().last_exit("lazy-harness-x") is None


def test_every_backend_implements_last_exit() -> None:
    from lazy_harness.scheduler.base import SchedulerBackend

    for backend in (LaunchdBackend(), SystemdBackend(), CronBackend()):
        assert isinstance(backend, SchedulerBackend)
        assert callable(backend.last_exit)


# --- views -------------------------------------------------------------


class _FakeBackend:
    """A backend with discover() and a scripted last_exit()."""

    def __init__(self, exits: dict[str, int | None]) -> None:
        from lazy_harness.scheduler.base import JobRecord, JobState

        self._exits = exits
        self._records = [
            JobRecord(name=n, label=f"lazy-harness-{n}", schedule="daily", state=JobState.LOADED)
            for n in exits
        ]

    def discover(self):
        return self._records

    def status(self):
        return [{"label": r.label, "status": "loaded"} for r in self._records]

    def last_exit(self, label: str) -> int | None:
        return self._exits[label.removeprefix("lazy-harness-")]


class _Plain(_FakeBackend):
    """A pre-widening backend: the attribute is absent, not None."""

    last_exit = None  # type: ignore[assignment]


def _status_output(monkeypatch, tmp_path: Path, backend) -> str:
    from click.testing import CliRunner

    from lazy_harness.cli import scheduler_cmd

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n[agent]\ntype = "claude-code"\n'
        '[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "~/.claude-p1"\n'
        '[knowledge]\nroot = ""\n'
    )
    monkeypatch.setattr(scheduler_cmd, "config_file", lambda: cfg)
    monkeypatch.setattr(scheduler_cmd, "detect_backend", lambda *a, **kw: backend)
    result = CliRunner().invoke(scheduler_cmd.scheduler, ["status"])
    assert result.exit_code == 0, result.output
    return result.output


def test_scheduler_status_shows_last_exit_next_to_state(monkeypatch, tmp_path: Path) -> None:
    out = _status_output(monkeypatch, tmp_path, _FakeBackend({"ok": 0, "bad": 1, "new": None}))
    lines = {
        label: line
        for line in out.splitlines()
        for label in ("lazy-harness-ok", "lazy-harness-bad", "lazy-harness-new")
        if line.rstrip().endswith(label) or f"{label} " in line
    }
    assert "exit 1" in lines["lazy-harness-bad"]
    assert "exit 0" in lines["lazy-harness-ok"]
    assert "exit" not in lines["lazy-harness-new"]


def test_scheduler_status_tolerates_a_backend_without_last_exit(monkeypatch, tmp_path) -> None:
    out = _status_output(monkeypatch, tmp_path, _Plain({"x": 1}))
    assert "lazy-harness-x" in out
    assert "exit " not in out


def _doctor_output(monkeypatch, tmp_path: Path, backend, home: Path) -> str:
    from click.testing import CliRunner

    from lazy_harness.cli import doctor_cmd

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n[agent]\ntype = "claude-code"\n'
        '[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "~/.claude-p1"\n'
        '[knowledge]\nroot = ""\n'
    )
    monkeypatch.setattr(doctor_cmd, "config_file", lambda: cfg)
    monkeypatch.setattr(doctor_cmd, "detect_backend", lambda *a, **kw: backend)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("COLUMNS", "500")
    result = CliRunner().invoke(doctor_cmd.doctor, [])
    # Exit 1 from unrelated checks is SystemExit; anything else is a crash.
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    return result.output


def _logs(home: Path, *names: str) -> None:
    log_dir = home / ".local/share/lazy-harness/logs"
    log_dir.mkdir(parents=True)
    for n in names:
        (log_dir / n).write_text("boom\n")


def test_doctor_warns_per_job_with_nonzero_exit_and_names_its_logs(monkeypatch, tmp_path) -> None:
    home = tmp_path / "home"
    _logs(home, "bad-stdout.log", "bad-stderr.log")
    out = " ".join(
        _doctor_output(
            monkeypatch, tmp_path, _FakeBackend({"ok": 0, "bad": 1, "new": None}), home
        ).split()
    )
    assert "bad — last run exited 1" in out
    assert "bad-stderr.log" in out and "bad-stdout.log" in out
    assert "lazy-harness-ok" not in out and "lazy-harness-new" not in out
    assert "ok — last run" not in out and "new — last run" not in out


def test_doctor_stays_silent_when_every_exit_is_zero_or_unknown(monkeypatch, tmp_path) -> None:
    out = _doctor_output(
        monkeypatch, tmp_path, _FakeBackend({"ok": 0, "new": None}), tmp_path / "home"
    )
    assert "Scheduled jobs" not in out


def test_doctor_tolerates_a_backend_without_last_exit(monkeypatch, tmp_path) -> None:
    out = _doctor_output(monkeypatch, tmp_path, _Plain({"x": 1}), tmp_path / "home")
    assert "Scheduled jobs" not in out
    assert "Traceback" not in out
