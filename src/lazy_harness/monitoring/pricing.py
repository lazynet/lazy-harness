"""Model pricing — defaults, config overrides, cost calculation."""

from __future__ import annotations

from dataclasses import dataclass

# Rates are per million tokens, from Anthropic's published table.
# `cache_create` is the 5-minute write (1.25x base input); `cache_create_1h`
# is the 1-hour write (2x base input). Claude Code reports which TTL a write
# used, and the harness bills the two separately — one shared rate prices a
# 1-hour write at 62.5% of what it costs.
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.5,
        "cache_create": 6.25,
        "cache_create_1h": 10.0,
    },
    "claude-opus-4-7": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.5,
        "cache_create": 6.25,
        "cache_create_1h": 10.0,
    },
    "claude-opus-4-8": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.5,
        "cache_create": 6.25,
        "cache_create_1h": 10.0,
    },
    "claude-opus-5": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.5,
        "cache_create": 6.25,
        "cache_create_1h": 10.0,
    },
    "claude-fable-5": {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 1.0,
        "cache_create": 12.5,
        "cache_create_1h": 20.0,
    },
    "claude-mythos-5": {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 1.0,
        "cache_create": 12.5,
        "cache_create_1h": 20.0,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.3,
        "cache_create": 3.75,
        "cache_create_1h": 6.0,
    },
    # Sonnet 5 is a tier below Sonnet 4.6, not the same one — the default
    # here used to be a copy of that row. The $2/$10 launch rate became the
    # standard price: the increase to $3/$15 scheduled for 2026-09-01 was
    # cancelled.
    "claude-sonnet-5": {
        "input": 2.0,
        "output": 10.0,
        "cache_read": 0.2,
        "cache_create": 2.5,
        "cache_create_1h": 4.0,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.0,
        "output": 5.0,
        "cache_read": 0.1,
        "cache_create": 1.25,
        "cache_create_1h": 2.0,
    },
    "claude-haiku-4-5": {
        "input": 1.0,
        "output": 5.0,
        "cache_read": 0.1,
        "cache_create": 1.25,
        "cache_create_1h": 2.0,
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


# Empty today. Sonnet 5's launch discount became the standard price, so it
# moved into DEFAULT_PRICING and the window it needed went away. The
# mechanism stays for the next launch discount.
INTRODUCTORY_PRICING: dict[str, IntroductoryRate] = {}


def is_pseudo_model(model: str) -> bool:
    """True for placeholders that stand in for a model without being one.

    Claude Code writes `<synthetic>` in the model field of messages that
    consumed no tokens. These will never have a rate, so `$0` is the correct
    answer rather than a hole in the pricing table — reporting them as
    unpriced fires the ingest warning on every run and trains the eye to
    skip it. Angle brackets are the marker; no real model id uses them.
    """
    return model.startswith("<") and model.endswith(">")


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

    `tokens` carries the two cache-write buckets separately:
    `cache_create` is the 5-minute write, `cache_create_1h` the 1-hour one.

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
    # A config override replaces a model's whole rate dict, so one written
    # against the older four-key shape carries no 1-hour rate. Falling back
    # to the published 2x multiplier keeps it from billing at zero.
    one_hour = rates.get("cache_create_1h", 2.0 * rates.get("input", 0.0))
    cost = (
        tokens.get("input", 0) * rates.get("input", 0)
        + tokens.get("output", 0) * rates.get("output", 0)
        + tokens.get("cache_read", 0) * rates.get("cache_read", 0)
        + tokens.get("cache_create", 0) * rates.get("cache_create", 0)
        + tokens.get("cache_create_1h", 0) * one_hour
    ) / 1_000_000
    return round(cost, 6)
