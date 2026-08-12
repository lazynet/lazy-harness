"""Model pricing — defaults, config overrides, cost calculation."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_create": 6.25},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_create": 6.25},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_create": 6.25},
    "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_create": 6.25},
    "claude-fable-5": {"input": 10.0, "output": 50.0, "cache_read": 1.0, "cache_create": 12.5},
    "claude-mythos-5": {"input": 10.0, "output": 50.0, "cache_read": 1.0, "cache_create": 12.5},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_create": 3.75},
    # Standing rate. The launch discount lives in INTRODUCTORY_PRICING below.
    "claude-sonnet-5": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_create": 3.75},
    "claude-haiku-4-5-20251001": {
        "input": 1.0,
        "output": 5.0,
        "cache_read": 0.1,
        "cache_create": 1.25,
    },
    "claude-haiku-4-5": {
        "input": 1.0,
        "output": 5.0,
        "cache_read": 0.1,
        "cache_create": 1.25,
    },
}


@dataclass(frozen=True)
class IntroductoryRate:
    """A launch discount that expires on a fixed date.

    Encoding the end date here rather than in a comment is what makes the
    reversion automatic: the standing rate is already the default, so the
    day the window closes nothing has to be remembered or edited.
    """

    since: str
    """First date the discount applies, inclusive, as YYYY-MM-DD."""

    through: str
    """Last date the discount applies, inclusive, as YYYY-MM-DD."""

    rates: dict[str, float]

    def covers(self, date: str) -> bool:
        return self.since <= date <= self.through


INTRODUCTORY_PRICING: dict[str, IntroductoryRate] = {
    "claude-sonnet-5": IntroductoryRate(
        since="2026-07-01",
        through="2026-08-31",
        rates={"input": 2.0, "output": 10.0, "cache_read": 0.2, "cache_create": 2.5},
    ),
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
    model: str,
    tokens: dict[str, int],
    pricing: dict[str, dict[str, float]],
    *,
    on: str | None = None,
) -> float:
    """Price one session's tokens.

    `on` is the session date (YYYY-MM-DD). It only matters for models with an
    entry in INTRODUCTORY_PRICING, where it selects the discounted rate for
    sessions inside the window. Without a date, the standing rate applies —
    a missing date should never under-charge.
    """
    rates = pricing.get(model)
    if not rates:
        return 0.0

    intro = INTRODUCTORY_PRICING.get(model)
    # A rate the caller overrode in config is the last word, so only apply the
    # discount while the table still holds the shipped default.
    if intro and on and intro.covers(on) and rates == DEFAULT_PRICING.get(model):
        rates = intro.rates
    cost = (
        tokens.get("input", 0) * rates.get("input", 0)
        + tokens.get("output", 0) * rates.get("output", 0)
        + tokens.get("cache_read", 0) * rates.get("cache_read", 0)
        + tokens.get("cache_create", 0) * rates.get("cache_create", 0)
    ) / 1_000_000
    return round(cost, 6)
