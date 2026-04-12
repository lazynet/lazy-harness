from pathlib import Path

from lazy_harness.selftest.checks.profile_check import check_profiles
from lazy_harness.selftest.result import CheckStatus

_BASE_TOML = (
    '[harness]\nversion = "1"\n'
    '[agent]\ntype = "claude-code"\n'
    '[knowledge]\npath = ""\n'
)


def _make_cfg(tmp_path: Path, profiles_section: str) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(_BASE_TOML + profiles_section)
    return cfg


def test_check_profiles_missing_config(tmp_path: Path):
    results = check_profiles(config_path=tmp_path / "nope.toml")
    assert any(r.status == CheckStatus.FAILED for r in results)


def test_check_profiles_dir_missing(tmp_path: Path):
    cfg = _make_cfg(
        tmp_path,
        '[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "/nonexistent/path/p1"\n',
    )
    results = check_profiles(config_path=cfg)
    assert any(r.name == "p1:exists" and r.status == CheckStatus.FAILED for r in results)


def test_check_profiles_happy_path(tmp_path: Path):
    profile_dir = tmp_path / "claude-p1"
    profile_dir.mkdir()
    (profile_dir / "CLAUDE.md").write_text("# Profile")
    (profile_dir / "settings.json").write_text('{"key": "value"}')

    cfg = _make_cfg(
        tmp_path,
        f'[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "{profile_dir}"\n',
    )
    results = check_profiles(config_path=cfg)
    statuses = {r.name: r.status for r in results}
    assert statuses["p1:exists"] == CheckStatus.PASSED
    assert statuses["p1:claude-md"] == CheckStatus.PASSED
    assert statuses["p1:settings-json"] == CheckStatus.PASSED


def test_check_profiles_missing_claude_md(tmp_path: Path):
    profile_dir = tmp_path / "claude-p1"
    profile_dir.mkdir()

    cfg = _make_cfg(
        tmp_path,
        f'[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "{profile_dir}"\n',
    )
    results = check_profiles(config_path=cfg)
    assert any(r.name == "p1:claude-md" and r.status == CheckStatus.WARNING for r in results)


def test_check_profiles_invalid_settings_json(tmp_path: Path):
    profile_dir = tmp_path / "claude-p1"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text("{bad json")

    cfg = _make_cfg(
        tmp_path,
        f'[profiles]\ndefault = "p1"\n\n[profiles.p1]\nconfig_dir = "{profile_dir}"\n',
    )
    results = check_profiles(config_path=cfg)
    assert any(r.name == "p1:settings-json" and r.status == CheckStatus.FAILED for r in results)
