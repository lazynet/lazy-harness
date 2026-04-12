from pathlib import Path

from lazy_harness.selftest.checks.hooks_check import check_hooks
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


def test_check_hooks_missing_config(tmp_path: Path):
    results = check_hooks(config_path=tmp_path / "nope.toml")
    assert any(r.status == CheckStatus.FAILED for r in results)


def test_check_hooks_no_hooks_declared(tmp_path: Path):
    cfg = _make_cfg(tmp_path)
    results = check_hooks(config_path=cfg)
    assert len(results) == 1
    assert results[0].name == "no-hooks"
    assert results[0].status == CheckStatus.PASSED


def test_check_hooks_builtin_resolves(tmp_path: Path):
    cfg = _make_cfg(
        tmp_path,
        '\n[hooks.PreToolUse]\nscripts = ["context-inject"]\n',
    )
    results = check_hooks(config_path=cfg)
    assert any(
        r.name == "PreToolUse:context-inject" and r.status == CheckStatus.PASSED
        for r in results
    )


def test_check_hooks_unknown_hook_warns(tmp_path: Path):
    cfg = _make_cfg(
        tmp_path,
        '\n[hooks.Stop]\nscripts = ["nonexistent-hook"]\n',
    )
    results = check_hooks(config_path=cfg)
    assert any(
        r.name == "Stop:nonexistent-hook" and r.status == CheckStatus.WARNING
        for r in results
    )
