"""Tests for model pricing."""

from __future__ import annotations

from pathlib import Path


def test_default_pricing_matches_litellm() -> None:
    """Defaults must mirror LiteLLM's model_prices_and_context_window.json.

    ccusage sources its pricing from LiteLLM; keeping ours aligned is the
    only way `lh status` cost numbers reconcile with `npx ccusage`. Values
    below are LiteLLM's per-million-token rates as of 2026-04 for the three
    Claude models the harness actively sees.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-opus-4-6"] == {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.5,
        "cache_create": 6.25,
    }
    assert pricing["claude-sonnet-4-6"] == {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.3,
        "cache_create": 3.75,
    }
    assert pricing["claude-haiku-4-5-20251001"] == {
        "input": 1.0,
        "output": 5.0,
        "cache_read": 0.1,
        "cache_create": 1.25,
    }


def test_calculate_cost() -> None:
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    pricing = default_pricing()
    tokens = {"input": 1000, "output": 500, "cache_read": 2000, "cache_create": 100}
    cost = calculate_cost("claude-opus-4-6", tokens, pricing)
    expected = (1000 * 5.0 + 500 * 25.0 + 2000 * 0.5 + 100 * 6.25) / 1_000_000
    assert abs(cost - expected) < 0.000001


def test_calculate_cost_unknown_model() -> None:
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    pricing = default_pricing()
    tokens = {"input": 1000, "output": 500, "cache_read": 0, "cache_create": 0}
    cost = calculate_cost("unknown-model", tokens, pricing)
    assert cost == 0.0


def test_load_pricing_with_config_overrides(config_dir: Path) -> None:
    from lazy_harness.monitoring.pricing import load_pricing

    pricing = load_pricing(
        overrides={
            "claude-opus-4-6": {
                "input": 20.0,
                "output": 100.0,
                "cache_read": 2.0,
                "cache_create": 25.0,
            }
        }
    )
    assert pricing["claude-opus-4-6"]["input"] == 20.0
    assert "claude-sonnet-4-6" in pricing
