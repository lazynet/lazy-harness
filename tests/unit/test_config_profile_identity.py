"""Tests for ProfileEntry.identity: optional field, validated name shape."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import ConfigError, load_config, save_config
from lazy_harness.core.profile_identity import profile_identity

BASE = (
    '[harness]\nversion = "1"\n[agent]\ntype = "claude-code"\n[profiles]\ndefault = "{default}"\n'
)


def _load(tmp_path: Path, body: str, default: str = "claude-personal"):
    p = tmp_path / "config.toml"
    p.write_text(BASE.format(default=default) + body)
    return load_config(p)


def test_profile_without_identity_is_unvalidated(tmp_path: Path) -> None:
    cfg = _load(tmp_path, '[profiles.p1]\nconfig_dir = "~/.x"\n', default="p1")
    assert cfg.profiles.items["p1"].identity == ""
    assert profile_identity("p1", cfg.profiles.items["p1"]) == "p1"


def test_identity_with_matching_name_loads(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        '[profiles.claude-personal]\nidentity = "personal"\nconfig_dir = "~/.claude-personal"\n',
    )
    assert profile_identity("claude-personal", cfg.profiles.items["claude-personal"]) == "personal"


def test_identity_with_suffix_loads(tmp_path: Path) -> None:
    _load(
        tmp_path,
        '[profiles.codex-personal-alt]\nidentity = "personal"\nagent = "codex"\n'
        'config_dir = "~/.codex-personal-alt"\n',
        default="codex-personal-alt",
    )


def test_name_not_matching_prefix_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"\[profiles\.personal\].*claude-personal"):
        _load(
            tmp_path,
            '[profiles.personal]\nidentity = "personal"\nconfig_dir = "~/.x"\n',
            default="personal",
        )


def test_wrong_agent_prefix_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"\[profiles\.claude-personal\].*codex-personal"):
        _load(
            tmp_path,
            '[profiles.claude-personal]\nidentity = "personal"\nagent = "codex"\n'
            'config_dir = "~/.x"\n',
        )


def test_empty_suffix_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"\[profiles\.claude-personal-\]"):
        _load(
            tmp_path,
            '[profiles.claude-personal-]\nidentity = "personal"\nconfig_dir = "~/.x"\n',
            default="claude-personal-",
        )


@pytest.mark.parametrize("bad", ["Personal", "_common", "a_b", "-x", "x-", ""])
def test_invalid_identity_token_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError, match=r"\[profiles\.claude-x\]\.identity"):
        _load(
            tmp_path,
            f'[profiles.claude-x]\nidentity = "{bad}"\nconfig_dir = "~/.x"\n',
            default="claude-x",
        )


@pytest.mark.parametrize(
    "toml_value",
    ["1", "true", "false", '["personal"]', "{ x = 1 }"],
    ids=["int", "bool-true", "bool-false", "list", "table"],
)
def test_non_string_identity_is_refused(tmp_path: Path, toml_value: str) -> None:
    with pytest.raises(ConfigError, match=r"\[profiles\.claude-x\]\.identity"):
        _load(
            tmp_path,
            f'[profiles.claude-x]\nidentity = {toml_value}\nconfig_dir = "~/.x"\n',
            default="claude-x",
        )


def test_identity_round_trips(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        '[profiles.claude-personal]\nidentity = "personal"\nconfig_dir = "~/.claude-personal"\n',
    )
    out = tmp_path / "out.toml"
    save_config(cfg, out)
    cfg2 = load_config(out)
    save_config(cfg2, out)
    cfg3 = load_config(out)
    assert cfg3.profiles.items["claude-personal"].identity == "personal"


def test_absent_identity_round_trips_absent(tmp_path: Path) -> None:
    cfg = _load(tmp_path, '[profiles.p1]\nconfig_dir = "~/.x"\n', default="p1")
    out = tmp_path / "out.toml"
    save_config(cfg, out)
    assert "identity" not in out.read_text()
