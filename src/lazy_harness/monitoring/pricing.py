"""Model pricing — defaults, config overrides, cost calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

ApiEquivalentStatus = Literal["priced", "unknown_model", "unknown_tier", "no_usage"]


@dataclass(frozen=True, slots=True)
class ApiPriceBasis:
    provider: str
    service_tier: str
    currency: str
    rate_table_version: str


@dataclass(frozen=True, slots=True)
class ApiEquivalentPrice:
    amount: float | None
    status: ApiEquivalentStatus
    basis: ApiPriceBasis | None = None


_OPENAI_API_RATE_VERSION = "openai-2026-09-19"
_ANTHROPIC_API_RATE_VERSION = "anthropic-2026-09-22"
_OPENAI_API_RATE_WINDOWS = {
    "gpt-5.6-sol": (date(2026, 9, 19), date(2026, 11, 21)),
    "gpt-6-astra": (date(2026, 9, 19), date(2026, 9, 19)),
}
_OPENAI_API_RATES: dict[tuple[str, str, str], dict[str, float]] = {
    ("gpt-5.6-sol", "standard", "short"): {
        "input": 4.0,
        "cache_read": 0.4,
        "cache_create": 5.0,
        "output": 20.0,
    },
    ("gpt-5.6-sol", "standard", "long"): {
        "input": 8.0,
        "cache_read": 0.8,
        "cache_create": 10.0,
        "output": 30.0,
    },
    ("gpt-6-astra", "standard", "short"): {
        "input": 10.0,
        "cache_read": 1.0,
        "cache_create": 12.5,
        "output": 50.0,
    },
    ("gpt-6-astra", "standard", "long"): {
        "input": 20.0,
        "cache_read": 2.0,
        "cache_create": 25.0,
        "output": 75.0,
    },
}


def _derived_context_class(tokens: dict[str, int], threshold: int | None) -> str | None:
    """Classify a response by the prompt the provider counted, not by the charge.

    The boundary applies to the whole prompt, cached half included, so the
    gross is reconstructed as `input + cache_read` — the exact inverse of the
    subtraction `CodexAdapter` applies (ADR-066). A cache *write* is prompt
    content the provider already counted inside its own input figure, so
    adding it here would count it twice.

    Classifying on the charged input instead would call a 300K prompt served
    90% from cache a short one. At the 97% cache-read rate this harness runs,
    that is the common case rather than the corner.
    """
    if threshold is None:
        return None
    gross = int(tokens.get("input", 0) or 0) + int(tokens.get("cache_read", 0) or 0)
    return "long" if gross > threshold else "short"


def price_api_response(
    model: str,
    tokens: dict[str, int],
    *,
    service_tier: str | None,
    context_class: str | None,
    on: str | None = None,
) -> ApiEquivalentPrice:
    """Price one response when every dimension *its table keys on* is evidenced.

    The bar is per provider, not per function (ADR-065). OpenAI rates key on
    `(model, service_tier, context_class)` inside a dated window, so pricing
    one without a context class would pick between two rates that differ 2x.
    Anthropic publishes one rate per model, so the same demand would refuse a
    figure it has everything it needs to produce. `API_RATE_TABLES` carries
    each table's declared dimensions and a test holds that declaration to the
    arity of the table's own keys.
    """
    buckets = ("input", "output", "cache_read", "cache_create", "cache_create_1h")
    if not any(int(tokens.get(name, 0) or 0) for name in buckets):
        return ApiEquivalentPrice(None, "no_usage")
    evidence = {"service_tier": service_tier, "context_class": context_class}
    anthropic = API_RATE_TABLES["anthropic"]
    if model in anthropic.rates:
        if any(evidence[dimension] is None for dimension in anthropic.required):
            return ApiEquivalentPrice(None, "unknown_tier")
        # `calculate_cost` is the same function `cost_for_billing_model`
        # calls, so the comparison figure and the per-token figure can never
        # drift apart into two answers for one published rate. The tier slot
        # is filled from the declaration rather than from the argument: while
        # Anthropic does not bill by tier the caller's "standard" is an
        # assumption, and recording it would invent the evidence.
        return ApiEquivalentPrice(
            calculate_cost(model, tokens, DEFAULT_PRICING, on=on),
            "priced",
            ApiPriceBasis(
                "anthropic",
                service_tier if "service_tier" in anthropic.required else "n/a",
                "USD",
                anthropic.version,
            ),
        )
    if model not in {key[0] for key in _OPENAI_API_RATES}:
        return ApiEquivalentPrice(None, "unknown_model")
    openai = API_RATE_TABLES["openai"]
    if any(evidence[dimension] is None for dimension in openai.required):
        return ApiEquivalentPrice(None, "unknown_tier")
    if context_class is None:
        context_class = _derived_context_class(tokens, openai.long_context_threshold)
    if context_class is None:
        return ApiEquivalentPrice(None, "unknown_tier")
    try:
        effective_on = date.fromisoformat(on) if on is not None else None
    except ValueError:
        return ApiEquivalentPrice(None, "unknown_tier")
    valid_from, valid_through = _OPENAI_API_RATE_WINDOWS[model]
    if effective_on is None or not (valid_from <= effective_on <= valid_through):
        return ApiEquivalentPrice(None, "unknown_tier")
    rates = _OPENAI_API_RATES.get((model, service_tier, context_class))
    if rates is None:
        return ApiEquivalentPrice(None, "unknown_tier")
    amount = sum(int(tokens.get(name, 0) or 0) * rate for name, rate in rates.items())
    return ApiEquivalentPrice(
        amount / 1_000_000,
        "priced",
        ApiPriceBasis("openai", service_tier, "USD", _OPENAI_API_RATE_VERSION),
    )


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
    # Fable 5.1 keeps Fable 5's $10/$50 and both write rates, but breaks the
    # 0.1x cache-read convention every other row follows: reads bill at
    # 0.025x base input ($0.25), the only exception in the published table.
    # Copying the fable-5 row would over-charge reads 4x — and reads are the
    # bulk of the tokens in a long session.
    "claude-fable-5-1": {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 0.25,
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
    "claude-mythos-5-1": {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 0.25,
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


@dataclass(frozen=True, slots=True)
class ApiRateTable:
    """One provider's published rates and the evidence its keys demand.

    `dimensions` names what a caller must supply beyond the model. It is a
    claim about `rates`, not a description of it: the gate test compares it
    against the arity of the table's own keys, so a provider that starts
    billing by tier or context cannot keep an empty declaration and go on
    being priced at whichever row happened to be first.
    """

    provider: str
    version: str
    dimensions: tuple[str, ...]
    """Every dimension this table's keys carry, beyond the model."""
    rates: dict[Any, dict[str, float]]
    required: tuple[str, ...] = ()
    """The subset a caller must evidence. The rest the table derives."""
    long_context_threshold: int | None = None
    """Prompt size above which the provider charges its long-context rates."""


API_RATE_TABLES: dict[str, ApiRateTable] = {
    "openai": ApiRateTable(
        provider="openai",
        version=_OPENAI_API_RATE_VERSION,
        dimensions=("service_tier", "context_class"),
        rates=_OPENAI_API_RATES,
        # The context class is a function of the prompt size, which the usage
        # record reports, so it is derived rather than awaited (ADR-067).
        required=("service_tier",),
        # "Prompts with >272K input tokens are priced at 2x input and 1.5x
        # output for the full request" — published on both models' pages, and
        # already encoded in the long rows above.
        long_context_threshold=272_000,
    ),
    "anthropic": ApiRateTable(
        provider="anthropic",
        version=_ANTHROPIC_API_RATE_VERSION,
        dimensions=(),
        rates=DEFAULT_PRICING,
    ),
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

# The ADR-050 `cost_source` vocabulary for a `MetricEvent`/`session_stats`
# row: what `cost_for_billing_model` below returns whenever it names a
# source at all (`None` is not a member — it is the absence of one, the
# unpriced-gap case `unknown_models` watches for). This is a different
# vocabulary from `lh exec`'s own `cost_source` field (see `cli/exec_cmd.py`
# `EXEC_COST_SOURCES`): the two happen to share a field name across two
# unrelated schemas, `MetricEvent` v3 and `lh.exec/v1`, but answer different
# questions — this one says whether per-token pricing applied and succeeded,
# exec's says which subsystem produced the number.
COST_SOURCES: tuple[str, ...] = ("pricing", "subscription")


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


def cost_for_billing_model(
    model: str,
    tokens: dict[str, int],
    pricing: dict[str, dict[str, float]],
    *,
    billing_model: str,
    on: str | None = None,
) -> tuple[float, str | None]:
    """Price one row according to its profile's billing model (ADR-050).

    A `flat_rate` row short-circuits pricing entirely: the subscription
    already paid for the usage, so consulting the per-token table would
    either double-count it or — for a model with no rate — misreport real
    spend as an unpriced gap. `cost_source` is the caller's cue for
    rendering and for `unknown_models`: `"subscription"` never fires it,
    `"pricing"` means the per-token table had a rate, and `None` is the one
    case that should — pricing was attempted and failed.
    """
    if billing_model == "flat_rate":
        return 0.0, "subscription"

    cost = calculate_cost(model, tokens, pricing, on=on)
    cost_source = "pricing" if (model in pricing or is_pseudo_model(model)) else None
    return cost, cost_source
