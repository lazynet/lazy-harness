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
    cfg = _make_cfg(tmp_path, "\n[scheduler]\nbackend = \"auto\"\n")
    results = check_scheduler(config_path=cfg)
    assert any(r.name == "backend" and r.status == CheckStatus.PASSED for r in results)
    assert any(r.name == "declared-jobs" and r.status == CheckStatus.PASSED for r in results)


def test_check_scheduler_backend_failure(tmp_path: Path):
    cfg = _make_cfg(tmp_path, "\n[scheduler]\nbackend = \"auto\"\n")
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
