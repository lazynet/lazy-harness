"""Tests for the lh config memory --init wizard."""

from __future__ import annotations

from pathlib import Path

import pytest


def _scripted_confirm(answers: list[bool]):
    """Returns a click.confirm-compatible callable that pops answers in order."""
    iterator = iter(answers)

    def _confirm(prompt: str, default: bool = False) -> bool:
        try:
            return next(iterator)
        except StopIteration:
            return default

    return _confirm


@pytest.mark.parametrize("existing", [False, True])
def test_memory_wizard_writes_block_when_engram_installed_and_user_confirms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    from lazy_harness.core.config import load_config, save_config
    from lazy_harness.memory import engram as engram_mod
    from lazy_harness.wizards.memory import wizard_memory

    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)
    cfg_path = tmp_path / "config.toml"
    if existing:
        cfg_path.write_text(
            '[harness]\nversion = "1"\n\n# Keep this comment.\n'
            '[memory.engram]\nversion = "2.1.0"\nbinary = "/usr/local/bin/engram"\n'
        )
    output: list[str] = []

    confirm = _scripted_confirm([True, True, False, True])

    wrote = wizard_memory(cfg_path, prompt_confirm=confirm, echo=output.append)

    assert wrote is True
    assert cfg_path.is_file()
    content = cfg_path.read_text()
    assert "[memory.engram]" in content
    assert "enabled = true" in content
    assert "git_sync = true" in content
    assert "cloud = false" in content
    assert 'version = "3.0.0"' in content
    assert 'version = "3.0.0"' in "\n".join(output)
    cfg = load_config(cfg_path)
    for _ in range(2):
        save_config(cfg, cfg_path)
        cfg = load_config(cfg_path)
        assert cfg.memory.engram.version == "3.0.0"
    if existing:
        assert cfg.memory.engram.binary == "/usr/local/bin/engram"
        assert "# Keep this comment." in cfg_path.read_text()


def test_memory_wizard_cancels_when_user_declines_final_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.memory import engram as engram_mod
    from lazy_harness.wizards.memory import wizard_memory

    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)
    cfg_path = tmp_path / "config.toml"

    confirm = _scripted_confirm([True, True, False, False])

    wrote = wizard_memory(cfg_path, prompt_confirm=confirm, echo=lambda _m: None)

    assert wrote is False
    assert not cfg_path.is_file()


def test_memory_wizard_cancels_when_user_aborts_at_install_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.memory import engram as engram_mod
    from lazy_harness.wizards.memory import wizard_memory

    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)
    cfg_path = tmp_path / "config.toml"

    confirm = _scripted_confirm([False])

    wrote = wizard_memory(cfg_path, prompt_confirm=confirm, echo=lambda _m: None)

    assert wrote is False
    assert not cfg_path.is_file()


def test_memory_wizard_when_engram_missing_prints_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.memory import engram as engram_mod
    from lazy_harness.wizards.memory import wizard_memory

    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)
    cfg_path = tmp_path / "config.toml"
    output: list[str] = []
    confirm = _scripted_confirm([False])

    wizard_memory(cfg_path, prompt_confirm=confirm, echo=output.append)

    joined = "\n".join(output)
    assert "Engram is not installed" in joined
    assert "brew install engram" in joined
    assert "3.0.0" in joined
