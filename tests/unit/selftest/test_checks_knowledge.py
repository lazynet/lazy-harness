from pathlib import Path

from lazy_harness.selftest.checks.knowledge_check import check_knowledge
from lazy_harness.selftest.result import CheckStatus

_BASE_TOML = (
    '[harness]\nversion = "1"\n'
    '[agent]\ntype = "claude-code"\n'
    '[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "~/.claude-p1"\n'
)


def _make_cfg(tmp_path: Path, knowledge_section: str) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(_BASE_TOML + knowledge_section)
    return cfg


def test_check_knowledge_missing_config(tmp_path: Path):
    results = check_knowledge(config_path=tmp_path / "nope.toml")
    assert any(r.status == CheckStatus.FAILED for r in results)


def test_check_knowledge_path_not_configured(tmp_path: Path):
    cfg = _make_cfg(tmp_path, '[knowledge]\npath = ""\n')
    results = check_knowledge(config_path=cfg)
    assert len(results) == 1
    assert results[0].name == "path"
    assert results[0].status == CheckStatus.PASSED


def test_check_knowledge_path_missing(tmp_path: Path):
    cfg = _make_cfg(tmp_path, f'[knowledge]\npath = "{tmp_path}/nonexistent"\n')
    results = check_knowledge(config_path=cfg)
    assert any(r.name == "path:exists" and r.status == CheckStatus.FAILED for r in results)


def test_check_knowledge_happy_path(tmp_path: Path):
    kp = tmp_path / "knowledge"
    kp.mkdir()
    (kp / "sessions").mkdir()
    (kp / "learnings").mkdir()

    cfg = _make_cfg(tmp_path, f'[knowledge]\npath = "{kp}"\n')
    results = check_knowledge(config_path=cfg)
    statuses = {r.name: r.status for r in results}
    assert statuses["path:exists"] == CheckStatus.PASSED
    assert statuses["path:writable"] == CheckStatus.PASSED
    assert statuses["subdir:sessions"] == CheckStatus.PASSED
    assert statuses["subdir:learnings"] == CheckStatus.PASSED


def test_check_knowledge_missing_subdirs_warn(tmp_path: Path):
    kp = tmp_path / "knowledge"
    kp.mkdir()

    cfg = _make_cfg(tmp_path, f'[knowledge]\npath = "{kp}"\n')
    results = check_knowledge(config_path=cfg)
    assert any(r.name == "subdir:sessions" and r.status == CheckStatus.WARNING for r in results)
    assert any(r.name == "subdir:learnings" and r.status == CheckStatus.WARNING for r in results)
