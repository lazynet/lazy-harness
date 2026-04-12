"""Model pricing — defaults, config overrides, cost calculation."""

from __future__ import annotations

DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_create": 18.75},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_create": 3.75},
    "claude-haiku-4-5-20251001": {
        "input": 0.8,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_create": 1.0,
    },
}


def default_pricing() -> dict[str, dict[str, float]]:
    return {k: dict(v) for k, v in DEFAULT_PRICING.items()}


def load_pricing(
    overrides: dict[str, dict[str, float]] | None = None,
) -> dict[str, dict[str, float]]:
    pricing = default_pricing()
    if overrides:
        for model, rates in overrides.items():
            pricing[model] = dict(rates)
    return pricing


def calculate_cost(
    model: str, tokens: dict[str, int], pricing: dict[str, dict[str, float]]
) -> float:
    rates = pricing.get(model)
    if not rates:
        return 0.0
    cost = (
        tokens.get("input", 0) * rates.get("input", 0)
        + tokens.get("output", 0) * rates.get("output", 0)
        + tokens.get("cache_read", 0) * rates.get("cache_read", 0)
        + tokens.get("cache_create", 0) * rates.get("cache_create", 0)
    ) / 1_000_000
    return round(cost, 6)
