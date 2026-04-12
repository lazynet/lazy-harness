"""Tests for model pricing."""

from __future__ import annotations

from pathlib import Path


def test_default_pricing() -> None:
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert "claude-opus-4-6" in pricing
    assert pricing["claude-opus-4-6"]["input"] == 15.0
    assert pricing["claude-opus-4-6"]["output"] == 75.0


def test_calculate_cost() -> None:
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    pricing = default_pricing()
    tokens = {"input": 1000, "output": 500, "cache_read": 2000, "cache_create": 100}
    cost = calculate_cost("claude-opus-4-6", tokens, pricing)
    expected = (1000 * 15.0 + 500 * 75.0 + 2000 * 1.5 + 100 * 18.75) / 1_000_000
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
