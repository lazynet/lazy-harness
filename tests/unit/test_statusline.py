"""Tests for the statusline formatter."""

from __future__ import annotations

import pytest


def _full_payload() -> dict:
    return {
        "model": {"display_name": "Sonnet 4.6"},
        "worktree": {"branch": "main"},
        "workspace": {"current_dir": "/Users/lazynet/repos/lazy/lazy-claudecode"},
        "context_window": {
            "total_input_tokens": 12_300,
            "total_output_tokens": 4_700,
            "remaining_percentage": 87,
        },
        "cost": {"total_cost_usd": 0.4321},
    }


def test_format_full_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.statusline import format_statusline

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-lazy")
    out = format_statusline(_full_payload())
    assert out == "lazy Sonnet 4.6 lazy-claudecode @main | 12K/5K tok $0.43 | 87% free"


def test_profile_label_default_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.statusline import format_statusline

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", "/tmp/whatever")
    out = format_statusline({})
    # Falls back to ~/.claude → 'default'
    assert out.startswith("default ")


def test_profile_label_for_flex(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.statusline import format_statusline

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-flex")
    out = format_statusline({})
    assert out.startswith("flex ")


def test_format_empty_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.statusline import format_statusline

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-lazy")
    out = format_statusline({})
    assert "lazy |" in out
    assert "0K/0K tok $0.00" in out
    assert "?% free" in out


def test_format_omits_unknown_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.statusline import format_statusline

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-lazy")
    out = format_statusline({"model": {"display_name": "?"}})
    assert "?" not in out.split("|")[0]


def test_format_omits_branch_and_dir_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.statusline import format_statusline

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-lazy")
    out = format_statusline({"model": {"display_name": "Opus 4.6"}})
    head = out.split("|")[0].strip()
    assert head == "lazy Opus 4.6"


def test_token_rounding(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.statusline import _to_k

    assert _to_k(0) == "0"
    assert _to_k(499) == "0"
    assert _to_k(500) == "1"
    assert _to_k(1_499) == "1"
    assert _to_k(1_500) == "2"
    assert _to_k(123_456) == "123"
    assert _to_k(None) == "0"
    assert _to_k("not a number") == "0"


def test_cost_rounding(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.statusline import format_statusline

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-lazy")
    out = format_statusline({"cost": {"total_cost_usd": 1.236}})
    assert "$1.24" in out


def test_robust_to_garbage_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.statusline import format_statusline

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/lazynet/.claude-lazy")
    # Wrong nested types — formatter must not crash
    out = format_statusline(
        {
            "model": "wrong-type",  # should be dict
            "context_window": [1, 2, 3],  # should be dict
            "cost": "free",
        }
    )
    assert out.startswith("lazy")
    assert "0K/0K" in out
