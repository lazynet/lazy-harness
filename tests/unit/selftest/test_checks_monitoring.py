import os
from pathlib import Path

import pytest

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.selftest.checks.monitoring_check import check_monitoring
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
    cfg = _make_cfg(tmp_path, '\n[monitoring]\nenabled = true\ndb = ""\n')
    results = check_monitoring(config_path=cfg)
    assert any(r.name == "db-path" and r.status == CheckStatus.FAILED for r in results)


def test_check_monitoring_permission_denied_directory_warns_not_fails(tmp_path: Path):
    """A metrics directory this environment cannot write to (sandboxed,
    read-only) is not proof the *configured* DB path is broken — it stays
    a WARNING (still non-green, but not a genuine, exit-code-affecting
    failure)."""
    db_dir = tmp_path / "metrics"
    db_dir.mkdir()
    db_path = db_dir / "m.db"
    MetricsDB(db_path).close()
    cfg = _make_cfg(tmp_path, f'\n[monitoring]\nenabled = true\ndb = "{db_path}"\n')

    os.chmod(db_dir, 0o500)
    try:
        results = check_monitoring(config_path=cfg)
    finally:
        os.chmod(db_dir, 0o700)

    statuses = {r.name: r for r in results}
    assert statuses["db-path"].status == CheckStatus.WARNING
    assert "permission" in statuses["db-path"].message.lower()


def test_check_monitoring_corrupt_db_stays_failed(tmp_path: Path):
    """A genuinely corrupt DB file is a real finding, not an environment
    limit — it must stay FAILED, not be reclassified as unverifiable."""
    db_path = tmp_path / "m.db"
    db_path.write_text("not a sqlite database")
    cfg = _make_cfg(tmp_path, f'\n[monitoring]\nenabled = true\ndb = "{db_path}"\n')

    results = check_monitoring(config_path=cfg)

    statuses = {r.name: r for r in results}
    assert statuses["db-path"].status == CheckStatus.FAILED


@pytest.mark.parametrize("errno_value", [13, 1])  # EACCES, EPERM
def test_check_monitoring_treats_eacces_and_eperm_as_permission_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, errno_value: int
) -> None:
    def raise_mkdir(self: Path, parents: bool = False, exist_ok: bool = False) -> None:
        raise OSError(errno_value, "denied")

    monkeypatch.setattr(Path, "mkdir", raise_mkdir)
    db_path = tmp_path / "sub" / "m.db"
    cfg = _make_cfg(tmp_path, f'\n[monitoring]\nenabled = true\ndb = "{db_path}"\n')

    results = check_monitoring(config_path=cfg)

    statuses = {r.name: r for r in results}
    assert statuses["db-path"].status == CheckStatus.WARNING


def test_check_monitoring_treats_other_errno_as_a_genuine_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno as errno_mod

    def raise_mkdir(self: Path, parents: bool = False, exist_ok: bool = False) -> None:
        raise OSError(errno_mod.ENOSPC, "no space left on device")

    monkeypatch.setattr(Path, "mkdir", raise_mkdir)
    db_path = tmp_path / "sub" / "m.db"
    cfg = _make_cfg(tmp_path, f'\n[monitoring]\nenabled = true\ndb = "{db_path}"\n')

    results = check_monitoring(config_path=cfg)

    statuses = {r.name: r for r in results}
    assert statuses["db-path"].status == CheckStatus.FAILED
