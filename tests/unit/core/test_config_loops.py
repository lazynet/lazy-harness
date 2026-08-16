"""Tests for the [loops] config section."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import Config, load_config, save_config


def test_defaults_to_injection_off(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[harness]\nversion = "1"\n')

    cfg = load_config(cfg_file)

    assert cfg.loops.inject_goal_prompt is False


def test_loads_an_explicit_true_through_a_full_cycle(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[harness]\nversion = "1"\n\n[loops]\ninject_goal_prompt = true\n')

    cfg = load_config(cfg_file)

    assert cfg.loops.inject_goal_prompt is True


def test_a_scalar_loops_value_does_not_crash_the_loader(tmp_path: Path) -> None:
    """MINOR 6: `loops_raw.get(...)` on a non-dict raises AttributeError,
    which metrics_cmd.py does not catch (it only catches ConfigError) and so
    tracebacks the command. Mirror the isinstance guard adjacent
    [context_inject] blocks already have."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('loops = true\n\n[harness]\nversion = "1"\n')

    cfg = load_config(cfg_file)

    assert cfg.loops.inject_goal_prompt is False


def test_survives_a_full_save_and_reload_round_trip(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg = Config()
    cfg.loops.inject_goal_prompt = True

    save_config(cfg, cfg_file)
    reloaded = load_config(cfg_file)

    assert reloaded.loops.inject_goal_prompt is True

    save_config(reloaded, cfg_file)
    reloaded_again = load_config(cfg_file)

    assert reloaded_again.loops.inject_goal_prompt is True
