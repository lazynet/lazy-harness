"""Tests for monitoring/views/profiles.py — _profile_counts helper."""

from __future__ import annotations

import json
from pathlib import Path


def test_hook_count_reads_settings_json(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views.profiles import _profile_counts

    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {"matcher": "", "hooks": [{"type": "command", "command": "x"}]},
                        {"matcher": "", "hooks": [{"type": "command", "command": "y"}]},
                    ],
                },
            }
        )
    )

    hooks, _ = _profile_counts(tmp_path)
    assert hooks == 2


def test_mcp_count_reads_claude_json_not_settings(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views.profiles import _profile_counts

    (tmp_path / "settings.json").write_text(
        json.dumps({"mcpServers": {"phantom1": {}, "phantom2": {}, "phantom3": {}}})
    )
    (tmp_path / ".claude.json").write_text(json.dumps({"mcpServers": {"qmd": {}, "engram": {}}}))

    _, mcps = _profile_counts(tmp_path)
    assert mcps == 2


def test_mcp_count_zero_when_claude_json_missing(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views.profiles import _profile_counts

    (tmp_path / "settings.json").write_text(json.dumps({"hooks": {}}))

    _, mcps = _profile_counts(tmp_path)
    assert mcps == 0


def test_counts_zero_when_dir_empty(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views.profiles import _profile_counts

    hooks, mcps = _profile_counts(tmp_path)
    assert hooks == 0
    assert mcps == 0


def test_counts_handle_corrupt_claude_json(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views.profiles import _profile_counts

    (tmp_path / ".claude.json").write_text("{not valid json")

    _, mcps = _profile_counts(tmp_path)
    assert mcps == 0
