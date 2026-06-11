"""Tests for the compound-loop worker entrypoint."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_worker_routes_dirs_through_agent_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-032 L3/L4: queue/log dirs must come from the configured agent
    adapter. With agent.type = "null" they must land under ~/.null even when
    CLAUDE_CONFIG_DIR points elsewhere."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    decoy_dir = tmp_path / "decoy-claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(decoy_dir))

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[agent]
type = "null"

[compound_loop]
enabled = true
"""
    )
    from lazy_harness.knowledge import compound_loop_worker as worker_mod

    monkeypatch.setattr(worker_mod, "config_file", lambda: cfg_file)

    rc = worker_mod.main()

    assert rc == 0
    assert (home / ".null" / "queue" / "done").is_dir()
    assert (home / ".null" / "logs" / "compound-loop.log").is_file()
    assert not decoy_dir.exists()


def test_worker_falls_back_to_claude_code_on_unknown_agent_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown agent.type in config.toml must not kill the worker: it falls
    back to the claude-code adapter and keeps draining the queue."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[agent]
type = "no-such-agent"

[compound_loop]
enabled = true
"""
    )
    from lazy_harness.knowledge import compound_loop_worker as worker_mod

    monkeypatch.setattr(worker_mod, "config_file", lambda: cfg_file)

    rc = worker_mod.main()

    assert rc == 0
    assert (claude_dir / "queue" / "done").is_dir()
    assert (claude_dir / "logs" / "compound-loop.log").is_file()
