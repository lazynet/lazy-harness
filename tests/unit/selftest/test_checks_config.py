from pathlib import Path

from lazy_harness.selftest.checks.config_check import check_config
from lazy_harness.selftest.result import CheckStatus


def test_check_config_missing(tmp_path: Path):
    results = check_config(config_path=tmp_path / "nope.toml")
    assert any(r.status == CheckStatus.FAILED for r in results)


def test_check_config_valid(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n'
        '[agent]\ntype = "claude-code"\n'
        '[profiles]\ndefault = "personal"\n'
        '[profiles.items.personal]\nconfig_dir = "~/.claude-personal"\n'
        '[knowledge]\npath = ""\n'
    )
    results = check_config(config_path=cfg)
    assert all(r.status == CheckStatus.PASSED for r in results)


def test_check_config_unknown_agent(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n'
        '[agent]\ntype = "unknown-agent"\n'
        '[profiles]\ndefault = "personal"\n'
        '[profiles.items.personal]\nconfig_dir = "~/.claude-personal"\n'
        '[knowledge]\npath = ""\n'
    )
    results = check_config(config_path=cfg)
    assert any(
        r.name == "agent-valid" and r.status == CheckStatus.FAILED for r in results
    )
