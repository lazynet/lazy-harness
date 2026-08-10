from pathlib import Path

import pytest

from lazy_harness.selftest.checks.knowledge_check import check_knowledge
from lazy_harness.selftest.result import CheckStatus

_BASE_TOML = (
    '[harness]\nversion = "1"\n'
    '[agent]\ntype = "claude-code"\n'
    '[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "~/.claude-p1"\n'
)

_MARKER = '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'


def _make_cfg(tmp_path: Path, knowledge_section: str) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(_BASE_TOML + knowledge_section)
    return cfg


@pytest.fixture(autouse=True)
def _no_env_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)


def test_check_knowledge_missing_config(tmp_path: Path):
    results = check_knowledge(config_path=tmp_path / "nope.toml")
    assert any(r.status == CheckStatus.FAILED for r in results)


def test_check_knowledge_path_missing(tmp_path: Path):
    cfg = _make_cfg(tmp_path, f'[knowledge]\nroot = "{tmp_path}/nonexistent"\n')
    results = check_knowledge(config_path=cfg)
    assert any(r.name == "path:exists" and r.status == CheckStatus.FAILED for r in results)


def test_check_knowledge_missing_marker_fails(tmp_path: Path):
    kp = tmp_path / "knowledge"
    kp.mkdir()

    cfg = _make_cfg(tmp_path, f'[knowledge]\nroot = "{kp}"\n')
    results = check_knowledge(config_path=cfg)
    assert any(r.name == "marker" and r.status == CheckStatus.FAILED for r in results)


def test_check_knowledge_happy_path(tmp_path: Path):
    kp = tmp_path / "knowledge"
    kp.mkdir()
    (kp / "knowledge.toml").write_text(_MARKER)
    (kp / "sessions").mkdir()
    (kp / "learnings").mkdir()

    cfg = _make_cfg(tmp_path, f'[knowledge]\nroot = "{kp}"\n')
    results = check_knowledge(config_path=cfg)
    statuses = {r.name: r.status for r in results}
    assert statuses["path:exists"] == CheckStatus.PASSED
    assert statuses["path:writable"] == CheckStatus.PASSED
    assert statuses["marker"] == CheckStatus.PASSED
    assert statuses["subdir:sessions"] == CheckStatus.PASSED
    assert statuses["subdir:learnings"] == CheckStatus.PASSED


def test_check_knowledge_subdir_names_follow_the_marker(tmp_path: Path):
    kp = tmp_path / "knowledge"
    kp.mkdir()
    (kp / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "logs"\nlearnings = "lessons"\n'
    )
    (kp / "logs").mkdir()
    (kp / "lessons").mkdir()

    cfg = _make_cfg(tmp_path, f'[knowledge]\nroot = "{kp}"\n')
    results = check_knowledge(config_path=cfg)
    statuses = {r.name: r.status for r in results}
    assert statuses["subdir:logs"] == CheckStatus.PASSED
    assert statuses["subdir:lessons"] == CheckStatus.PASSED


def test_check_knowledge_missing_subdirs_warn(tmp_path: Path):
    kp = tmp_path / "knowledge"
    kp.mkdir()
    (kp / "knowledge.toml").write_text(_MARKER)

    cfg = _make_cfg(tmp_path, f'[knowledge]\nroot = "{kp}"\n')
    results = check_knowledge(config_path=cfg)
    assert any(r.name == "subdir:sessions" and r.status == CheckStatus.WARNING for r in results)
    assert any(r.name == "subdir:learnings" and r.status == CheckStatus.WARNING for r in results)
