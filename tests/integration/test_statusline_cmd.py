"""Integration tests for `lh statusline`."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli


def test_statusline_renders_payload_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-flex")
    payload = {
        "model": {"display_name": "Sonnet 4.6"},
        "workspace": {"current_dir": "/Users/lazynet/repos/flex/foo"},
        "context_window": {
            "total_input_tokens": 8_000,
            "total_output_tokens": 2_000,
            "remaining_percentage": 91,
        },
        "cost": {"total_cost_usd": 0.12},
    }
    runner = CliRunner()
    result = runner.invoke(cli, ["statusline"], input=json.dumps(payload))
    assert result.exit_code == 0, result.output
    out = result.output.strip()
    assert out == "flex Sonnet 4.6 foo | 8K/2K tok $0.12 | 91% free"


def test_statusline_handles_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-lazy")
    runner = CliRunner()
    result = runner.invoke(cli, ["statusline"], input="not-json")
    assert result.exit_code == 0, result.output
    assert result.output.strip().startswith("lazy")


def test_statusline_handles_empty_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-lazy")
    runner = CliRunner()
    result = runner.invoke(cli, ["statusline"], input="")
    assert result.exit_code == 0, result.output


def test_statusline_handles_array_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-lazy")
    runner = CliRunner()
    result = runner.invoke(cli, ["statusline"], input="[1, 2, 3]")
    assert result.exit_code == 0
    assert "lazy" in result.output
