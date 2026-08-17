from pathlib import Path
from unittest.mock import patch

from lazy_harness.selftest.checks.scheduler_check import check_scheduler
from lazy_harness.selftest.result import CheckStatus

_BASE_TOML = (
    '[harness]\nversion = "1"\n'
    '[agent]\ntype = "claude-code"\n'
    '[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "~/.claude-p1"\n'
    '[knowledge]\nroot = ""\n'
)


def _make_cfg(tmp_path: Path, extra: str = "") -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(_BASE_TOML + extra)
    return cfg


def test_check_scheduler_missing_config(tmp_path: Path):
    results = check_scheduler(config_path=tmp_path / "nope.toml")
    assert any(r.status == CheckStatus.FAILED for r in results)


def test_check_scheduler_happy_path(tmp_path: Path):
    cfg = _make_cfg(tmp_path, '\n[scheduler]\nbackend = "auto"\n')
    results = check_scheduler(config_path=cfg)
    assert any(r.name == "backend" and r.status == CheckStatus.PASSED for r in results)
    assert any(r.name == "declared-jobs" and r.status == CheckStatus.PASSED for r in results)


def test_check_scheduler_backend_failure(tmp_path: Path):
    cfg = _make_cfg(tmp_path, '\n[scheduler]\nbackend = "auto"\n')
    with patch(
        "lazy_harness.selftest.checks.scheduler_check.detect_backend",
        side_effect=RuntimeError("no backend"),
    ):
        results = check_scheduler(config_path=cfg)
    assert any(r.name == "backend" and r.status == CheckStatus.FAILED for r in results)


def test_check_scheduler_no_declared_jobs(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    results = check_scheduler(config_path=cfg)
    jobs_result = next((r for r in results if r.name == "declared-jobs"), None)
    assert jobs_result is not None
    assert jobs_result.status == CheckStatus.PASSED
    assert "0 jobs" in jobs_result.message


def _cfg_with_a_job(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n'
        "[scheduler]\n"
        'backend = "systemd"\n\n'
        "[scheduler.jobs.qmd-sync]\n"
        'schedule = "0 6 * * *"\n'
        'command = "qmd sync"\n'
    )
    return cfg


def test_linger_check_fails_when_lingering_is_off(tmp_path) -> None:
    """A machine whose scheduled jobs cannot fire is not healthy.

    `systemctl --user enable --now` reports success either way, so this is
    the only thing that distinguishes installed from installed-and-running.
    """
    import subprocess

    from lazy_harness.selftest.checks.scheduler_check import check_linger
    from lazy_harness.selftest.result import CheckStatus

    def runner(argv):
        return subprocess.CompletedProcess(argv, 0, stdout="Linger=no", stderr="")

    results = check_linger(config_path=_cfg_with_a_job(tmp_path), runner=runner)
    assert results[0].status == CheckStatus.FAILED
    assert "enable-linger" in results[0].message


def test_linger_check_passes_when_lingering_is_on(tmp_path) -> None:
    import subprocess

    from lazy_harness.selftest.checks.scheduler_check import check_linger
    from lazy_harness.selftest.result import CheckStatus

    def runner(argv):
        return subprocess.CompletedProcess(argv, 0, stdout="Linger=yes", stderr="")

    results = check_linger(config_path=_cfg_with_a_job(tmp_path), runner=runner)
    assert results[0].status == CheckStatus.PASSED


def test_linger_check_is_silent_on_a_non_systemd_backend(tmp_path) -> None:
    """Lingering is a systemd concept; reporting on it elsewhere is noise."""
    from lazy_harness.selftest.checks.scheduler_check import check_linger

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n[scheduler]\nbackend = "launchd"\n\n'
        '[scheduler.jobs.x]\nschedule = "0 6 * * *"\ncommand = "true"\n'
    )
    assert check_linger(config_path=cfg) == []


def test_linger_check_is_silent_when_no_jobs_are_declared(tmp_path) -> None:
    from lazy_harness.selftest.checks.scheduler_check import check_linger

    cfg = tmp_path / "config.toml"
    cfg.write_text('[harness]\nversion = "1"\n\n[scheduler]\nbackend = "systemd"\n')
    assert check_linger(config_path=cfg) == []


def test_linger_check_resolves_the_user_without_env_vars(tmp_path, monkeypatch) -> None:
    """`lh selftest` can run from a systemd or cron context, where USER is unset.

    Falling back to "" made the check ask loginctl about an empty user and
    report WARNING — a non-answer in exactly the environment the check exists
    to reason about.
    """
    import subprocess

    from lazy_harness.selftest.checks.scheduler_check import check_linger
    from lazy_harness.selftest.result import CheckStatus

    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("LOGNAME", raising=False)

    asked: list[str] = []

    def runner(argv):
        asked.append(argv[2])
        return subprocess.CompletedProcess(argv, 0, stdout="Linger=yes", stderr="")

    results = check_linger(config_path=_cfg_with_a_job(tmp_path), runner=runner)

    assert asked and asked[0], "loginctl was asked about an empty user"
    assert results[0].status == CheckStatus.PASSED


def _jobs_toml() -> str:
    return (
        '\n[scheduler]\nbackend = "auto"\n\n'
        '[scheduler.jobs.qmd-sync]\nschedule = "0 6 * * *"\ncommand = "/usr/bin/true"\n'
    )


class _Backend:
    """A backend whose drift answer is the thing under test."""

    def __init__(self, drift_result):
        self._drift = drift_result

    def label_for(self, job):
        return f"x.{job.name}"

    def status(self):
        return [{"label": "x.qmd-sync", "status": "loaded"}]

    def drift(self, jobs):
        return self._drift


def test_stale_units_are_reported_and_named(tmp_path: Path):
    """A job can be installed, loaded and counted, and still carry content
    from a superseded generator. The count comparison cannot see that."""
    from lazy_harness.scheduler.base import DriftState, JobDrift

    cfg = _make_cfg(tmp_path, _jobs_toml())
    backend = _Backend([JobDrift("qmd-sync", DriftState.STALE, "EnvironmentVariables")])
    with patch("lazy_harness.selftest.checks.scheduler_check.detect_backend", return_value=backend):
        results = check_scheduler(config_path=cfg)

    stale = [r for r in results if r.name == "units-stale"]
    assert stale, [r.name for r in results]
    assert stale[0].status == CheckStatus.WARNING
    assert "qmd-sync" in stale[0].message
    assert "scheduler install" in stale[0].message


def test_current_units_pass(tmp_path: Path):
    from lazy_harness.scheduler.base import DriftState, JobDrift

    cfg = _make_cfg(tmp_path, _jobs_toml())
    backend = _Backend([JobDrift("qmd-sync", DriftState.CURRENT)])
    with patch("lazy_harness.selftest.checks.scheduler_check.detect_backend", return_value=backend):
        results = check_scheduler(config_path=cfg)

    stale = [r for r in results if r.name == "units-stale"]
    assert stale and stale[0].status == CheckStatus.PASSED


def test_undeterminable_drift_is_not_reported_as_current(tmp_path: Path):
    """UNKNOWN means the comparison did not happen, which is not a pass."""
    from lazy_harness.scheduler.base import DriftState, JobDrift

    cfg = _make_cfg(tmp_path, _jobs_toml())
    backend = _Backend([JobDrift("qmd-sync", DriftState.UNKNOWN, "crontab unavailable")])
    with patch("lazy_harness.selftest.checks.scheduler_check.detect_backend", return_value=backend):
        results = check_scheduler(config_path=cfg)

    stale = [r for r in results if r.name == "units-stale"]
    assert stale and stale[0].status == CheckStatus.WARNING
    assert "crontab unavailable" in stale[0].message


def test_absent_units_do_not_count_as_stale(tmp_path: Path):
    """Not installed is what the count check already reports; saying it twice
    in different words makes the output harder to act on, not easier."""
    from lazy_harness.scheduler.base import DriftState, JobDrift

    cfg = _make_cfg(tmp_path, _jobs_toml())
    backend = _Backend([JobDrift("qmd-sync", DriftState.ABSENT)])
    with patch("lazy_harness.selftest.checks.scheduler_check.detect_backend", return_value=backend):
        results = check_scheduler(config_path=cfg)

    stale = [r for r in results if r.name == "units-stale"]
    assert stale and stale[0].status == CheckStatus.PASSED


def test_a_backend_without_drift_support_is_skipped_not_failed(tmp_path: Path):
    """Degrade rather than crash: `lh selftest` must survive a backend that
    predates this check."""
    cfg = _make_cfg(tmp_path, _jobs_toml())

    class Old:
        def label_for(self, job):
            return f"x.{job.name}"

        def status(self):
            return [{"label": "x.qmd-sync", "status": "loaded"}]

    with patch("lazy_harness.selftest.checks.scheduler_check.detect_backend", return_value=Old()):
        results = check_scheduler(config_path=cfg)

    assert not [r for r in results if r.name == "units-stale"]
    assert all(r.status != CheckStatus.FAILED for r in results)


def test_a_real_backend_feeds_the_check_end_to_end(tmp_path: Path):
    """The seam between `drift()` and the check is duck-typed.

    Every other test here injects a stub returning canned `JobDrift` values,
    and every backend test calls `drift()` directly. Nothing composed the two,
    so a signature or return-shape mismatch would pass both suites and fail
    only on a real machine — which is how `label_for` on the Protocol but
    `_label` on the backend made `isinstance` False on the only platform that
    installs anything.
    """
    import subprocess

    from lazy_harness.scheduler.cron import CronBackend

    class Fake:
        def __init__(self):
            self.content = ""

        def __call__(self, argv, *, input=None):  # noqa: A002
            if argv[1:] == ["-l"]:
                if not self.content:
                    return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no crontab")
                return subprocess.CompletedProcess(argv, 0, stdout=self.content, stderr="")
            self.content = input or ""
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    cfg = _make_cfg(tmp_path, _jobs_toml())
    fake = Fake()
    backend = CronBackend(runner=fake)
    from lazy_harness.scheduler.base import SchedulerJob

    backend.install([SchedulerJob(name="qmd-sync", schedule="0 6 * * *", command="/usr/bin/true")])

    with patch("lazy_harness.selftest.checks.scheduler_check.detect_backend", return_value=backend):
        clean = check_scheduler(config_path=cfg)
        assert [r for r in clean if r.name == "units-stale"][0].status == CheckStatus.PASSED

        # Now age the block the way an upgrade would.
        path_line = next(ln for ln in fake.content.splitlines() if ln.startswith("PATH="))
        fake.content = fake.content.replace(path_line, "PATH=/opt/old/bin")
        aged = check_scheduler(config_path=cfg)

    stale = [r for r in aged if r.name == "units-stale"][0]
    assert stale.status == CheckStatus.WARNING
    assert "qmd-sync" in stale.message
