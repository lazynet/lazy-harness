from pathlib import Path
from unittest.mock import patch

from lazy_harness.selftest.checks.scheduler_check import check_scheduler
from lazy_harness.selftest.result import CheckStatus

_BASE_TOML = (
    '[harness]\nversion = "1"\n'
    '[agent]\ntype = "claude-code"\n'
    '[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "~/.claude-p1"\n'
    '[knowledge]\npath = ""\n'
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
