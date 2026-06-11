"""Tests for cross-platform path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_config_dir_default_unix(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    from lazy_harness.core.paths import config_dir

    assert config_dir() == home_dir / ".config" / "lazy-harness"


def test_config_dir_xdg_override(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = home_dir / "custom-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(custom))
    from importlib import reload

    import lazy_harness.core.paths as paths_mod

    reload(paths_mod)
    assert paths_mod.config_dir() == custom / "lazy-harness"


def test_config_dir_env_override(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = home_dir / "explicit"
    monkeypatch.setenv("LH_CONFIG_DIR", str(custom))
    from importlib import reload

    import lazy_harness.core.paths as paths_mod

    reload(paths_mod)
    assert paths_mod.config_dir() == custom


def test_data_dir_default_unix(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    from lazy_harness.core.paths import data_dir

    assert data_dir() == home_dir / ".local" / "share" / "lazy-harness"


def test_cache_dir_default_unix(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    from lazy_harness.core.paths import cache_dir

    assert cache_dir() == home_dir / ".cache" / "lazy-harness"


def test_config_file_path(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_file

    result = config_file()
    assert result.name == "config.toml"
    assert "lazy-harness" in str(result)


def test_expand_user_path() -> None:
    from lazy_harness.core.paths import expand_path

    result = expand_path("~/projects")
    assert "~" not in str(result)
    assert result.is_absolute()


def test_contract_path(home_dir: Path) -> None:
    from lazy_harness.core.paths import contract_path

    full = home_dir / "projects" / "foo"
    result = contract_path(full)
    assert result.startswith("~")
    assert "foo" in result


def test_agent_runtime_dir_uses_adapter_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.core.paths import agent_runtime_dir

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/fake-claude")
    assert agent_runtime_dir(ClaudeCodeAdapter()) == Path("/tmp/fake-claude")


def test_agent_runtime_dir_falls_back_to_global_config_link(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.core.paths import agent_runtime_dir

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert agent_runtime_dir(ClaudeCodeAdapter()) == home_dir / ".claude"


def test_agent_runtime_dir_falls_back_to_dotted_agent_name(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents.registry import NullAdapter
    from lazy_harness.core.paths import agent_runtime_dir

    # NullAdapter has no env var and no global config link.
    assert agent_runtime_dir(NullAdapter()) == home_dir / ".null"
