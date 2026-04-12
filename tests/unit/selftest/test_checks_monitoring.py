from pathlib import Path

from lazy_harness.selftest.checks.monitoring_check import check_monitoring
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


def test_check_monitoring_missing_config(tmp_path: Path):
    results = check_monitoring(config_path=tmp_path / "nope.toml")
    assert any(r.status == CheckStatus.FAILED for r in results)


def test_check_monitoring_disabled(tmp_path: Path):
    cfg = _make_cfg(tmp_path, "\n[monitoring]\nenabled = false\n")
    results = check_monitoring(config_path=cfg)
    assert len(results) == 1
    assert results[0].name == "disabled"
    assert results[0].status == CheckStatus.PASSED


def test_check_monitoring_happy_path(tmp_path: Path):
    db_path = tmp_path / "metrics.db"
    cfg = _make_cfg(
        tmp_path,
        f'\n[monitoring]\nenabled = true\ndb = "{db_path}"\n',
    )
    results = check_monitoring(config_path=cfg)
    statuses = {r.name: r.status for r in results}
    assert statuses["db-path"] == CheckStatus.PASSED
    assert statuses["pricing"] == CheckStatus.PASSED


def test_check_monitoring_no_db_path(tmp_path: Path):
    cfg = _make_cfg(tmp_path, "\n[monitoring]\nenabled = true\ndb = \"\"\n")
    results = check_monitoring(config_path=cfg)
    assert any(r.name == "db-path" and r.status == CheckStatus.FAILED for r in results)
