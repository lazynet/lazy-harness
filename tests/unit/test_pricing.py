"""Tests for model pricing."""

from __future__ import annotations

from pathlib import Path

import pytest


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
        "cache_create_1h": 10.0,
    }
    assert pricing["claude-sonnet-4-6"] == {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.3,
        "cache_create": 3.75,
        "cache_create_1h": 6.0,
    }
    assert pricing["claude-haiku-4-5-20251001"] == {
        "input": 1.0,
        "output": 5.0,
        "cache_read": 0.1,
        "cache_create": 1.25,
        "cache_create_1h": 2.0,
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


def test_default_pricing_includes_opus_4_7() -> None:
    """claude-opus-4-7 must carry the same per-token rates as claude-opus-4-6.

    Both models sit in the same Claude 4 Opus tier with identical LiteLLM
    rate cards as of 2026-04. Without this entry calculate_cost silently
    returns 0.0 for all opus-4-7 sessions.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-opus-4-7"] == {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.5,
        "cache_create": 6.25,
        "cache_create_1h": 10.0,
    }


def test_default_pricing_includes_opus_4_8() -> None:
    """claude-opus-4-8 must carry the same per-token rates as the opus tier.

    Opus 4.8 (released 2026-05) sits in the same Claude 4 Opus tier with
    $5/$25 per-million input/output LiteLLM rates. Without this entry
    calculate_cost silently returns 0.0 for all opus-4-8 sessions.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-opus-4-8"] == {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.5,
        "cache_create": 6.25,
        "cache_create_1h": 10.0,
    }


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


def test_default_pricing_includes_fable_5() -> None:
    """claude-fable-5 must carry the official $10/$50 per-million rates.

    Fable 5 is priced above the Opus tier at $10/$50 per-million
    input/output. Cache rates follow the table convention: read = 0.1x
    input, create = 1.25x input. Without this entry calculate_cost
    silently returns 0.0 for all fable-5 sessions.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-fable-5"] == {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 1.0,
        "cache_create": 12.5,
        "cache_create_1h": 20.0,
    }


def test_sonnet_5_is_priced_at_its_own_rate_not_sonnet_4_6s() -> None:
    """claude-sonnet-5 bills $2/$10, not Sonnet 4.6's $3/$15.

    The default entry was a copy of the claude-sonnet-4-6 row. Anthropic's
    published table prices Sonnet 5 at $2 input / $10 output / $0.20 cache
    read / $2.50 5m write / $4 1h write — a tier below Sonnet 4.6, not the
    same one. The $2/$10 launch rate is now the standard price: the
    increase to $3/$15 scheduled for 2026-09-01 was cancelled.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-sonnet-5"] == {
        "input": 2.0,
        "output": 10.0,
        "cache_read": 0.2,
        "cache_create": 2.5,
        "cache_create_1h": 4.0,
    }
    assert pricing["claude-sonnet-5"] != pricing["claude-sonnet-4-6"]


def test_no_introductory_window_is_active() -> None:
    """Sonnet 5's launch discount became the standard price.

    Anthropic cancelled the 2026-09-01 increase to $3/$15, so the window
    has nothing left to express and the discounted rates moved into
    DEFAULT_PRICING. The IntroductoryRate mechanism stays for the next
    launch discount; the table it drives is empty.
    """
    from lazy_harness.monitoring.pricing import INTRODUCTORY_PRICING

    assert INTRODUCTORY_PRICING == {}


def _sonnet_cost(on: str | None) -> float:
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    return calculate_cost(
        "claude-sonnet-5",
        {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_create": 0},
        default_pricing(),
        on=on,
    )


def test_sonnet_5_bills_the_same_rate_on_either_side_of_the_old_window() -> None:
    """The cancelled 2026-09-01 increase must not fire.

    An expiry that reverts to $3/$15 would silently inflate every reported
    sonnet-5 cost by 50% from the day after the old window closed.
    """
    assert _sonnet_cost("2026-08-31") == pytest.approx(2.0)
    assert _sonnet_cost("2026-09-01") == pytest.approx(2.0)


def test_a_session_before_the_old_window_bills_the_same_rate() -> None:
    assert _sonnet_cost("2026-06-01") == pytest.approx(2.0)


def test_an_undated_session_bills_the_standing_rate() -> None:
    """With no date, bill at the standing rate rather than under-charging."""
    assert _sonnet_cost(None) == pytest.approx(2.0)


def test_a_config_override_beats_the_shipped_default() -> None:
    """A user-supplied rate is the last word."""
    from lazy_harness.monitoring.pricing import calculate_cost, load_pricing

    pricing = load_pricing(
        overrides={
            "claude-sonnet-5": {
                "input": 99.0,
                "output": 0.0,
                "cache_read": 0.0,
                "cache_create": 0.0,
            }
        }
    )
    cost = calculate_cost(
        "claude-sonnet-5",
        {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_create": 0},
        pricing,
        on="2026-08-12",
    )
    assert cost == pytest.approx(99.0)


def test_a_model_without_a_window_ignores_the_date() -> None:
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    tokens = {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_create": 0}
    pricing = default_pricing()
    assert calculate_cost("claude-opus-5", tokens, pricing, on="2026-08-12") == pytest.approx(5.0)
    assert calculate_cost("claude-opus-5", tokens, pricing, on="2026-09-01") == pytest.approx(5.0)


def test_default_pricing_includes_opus_5() -> None:
    """claude-opus-5 must carry the standard $5/$25 Opus-tier rates.

    Opus 5 (released 2026-07) is a drop-in upgrade at Opus 4.8's pricing.
    Cache rates follow the table convention: read = 0.1x input, create =
    1.25x input. Without this entry calculate_cost silently returns 0.0 for
    all opus-5 sessions.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-opus-5"] == {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.5,
        "cache_create": 6.25,
        "cache_create_1h": 10.0,
    }


def test_calculate_cost_opus_5_is_not_free() -> None:
    """An opus-5 session must produce a non-zero cost.

    Regression guard for the silent-zero path: calculate_cost returns 0.0
    for any model missing from the pricing table, so an unpriced opus-5
    session is indistinguishable from a free one on `lh status`.
    """
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    tokens = {"input": 1000, "output": 500, "cache_read": 2000, "cache_create": 100}
    cost = calculate_cost("claude-opus-5", tokens, default_pricing())
    expected = (1000 * 5.0 + 500 * 25.0 + 2000 * 0.5 + 100 * 6.25) / 1_000_000
    assert abs(cost - expected) < 0.000001


def test_default_pricing_includes_the_haiku_alias() -> None:
    """The dated Haiku id and its bare alias must both be priced.

    Every other model is keyed by its bare alias; Haiku is keyed only by
    `claude-haiku-4-5-20251001`. A session reported under the alias would
    price at 0.0 — and Haiku carries more sessions than any other model.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-haiku-4-5"] == pricing["claude-haiku-4-5-20251001"]


def test_default_pricing_includes_mythos_5() -> None:
    """claude-mythos-5 carries the same rates as claude-fable-5."""
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-mythos-5"] == pricing["claude-fable-5"]


def test_default_pricing_includes_fable_5_1() -> None:
    """claude-fable-5-1 is the model this profile actually runs on.

    It shares Fable 5's $10/$50 and both write rates, so the only number
    worth pinning is the cache read: 0.025x base input, not the 0.1x every
    other row uses. Without the entry the sessions price at 0.0 and the
    monthly total silently under-reports.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-fable-5-1"] == {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 0.25,
        "cache_create": 12.5,
        "cache_create_1h": 20.0,
    }


def test_fable_5_1_cache_reads_are_cheaper_than_fable_5s() -> None:
    """The 0.025x read multiplier is Fable 5.1-only — don't copy the 5 row.

    Reads dominate token volume in a long session, so pricing them at
    Fable 5's $1 would over-charge the bucket that matters most by 4x.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-fable-5-1"]["cache_read"] < pricing["claude-fable-5"]["cache_read"]


def test_default_pricing_includes_mythos_5_1() -> None:
    """claude-mythos-5-1 carries the same rates as claude-fable-5-1.

    Including the 0.025x cache read — the published table lists the two
    models on one line.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert pricing["claude-mythos-5-1"] == pricing["claude-fable-5-1"]


def test_synthetic_is_recognised_as_a_pseudo_model() -> None:
    """Claude Code emits `<synthetic>` for messages that consumed nothing.

    It has no rate and never will, so $0 is the right answer rather than a
    gap in the table — flagging it as unpriced turns the warning into noise
    on every single ingest.
    """
    from lazy_harness.monitoring.pricing import is_pseudo_model

    assert is_pseudo_model("<synthetic>")


def test_angle_bracketed_names_are_pseudo_models() -> None:
    """Claude Code marks non-model placeholders with angle brackets."""
    from lazy_harness.monitoring.pricing import is_pseudo_model

    assert is_pseudo_model("<none>")


def test_real_models_are_not_pseudo_models() -> None:
    from lazy_harness.monitoring.pricing import is_pseudo_model

    assert not is_pseudo_model("claude-opus-5")
    assert not is_pseudo_model("claude-future-model-99")
    assert not is_pseudo_model("")


# Five real `lh exec` calls from 2026-08-31, taken from the metrics
# pipeline and priced by hand against Anthropic's published table. Every
# cache write in this traffic carried a 1-hour TTL.
MEASURED_SESSIONS = [
    ("map-tasks", "claude-sonnet-5", 2, 141, 26168, 26038, 0.1108),
    ("map-findings", "claude-sonnet-5", 4, 628, 78923, 27386, 0.1316),
    ("map-articles", "claude-sonnet-5", 6, 4405, 134665, 50500, 0.2730),
    ("map-projects", "claude-sonnet-5", 6, 9594, 133239, 190048, 0.8828),
    ("reduce", "claude-opus-5", 10, 14607, 267362, 55875, 1.0577),
]


@pytest.mark.parametrize(
    ("item", "model", "inp", "out", "cache_read", "cache_create_1h", "expected"),
    MEASURED_SESSIONS,
)
def test_measured_sessions_price_at_their_verified_cost(
    item: str,
    model: str,
    inp: int,
    out: int,
    cache_read: int,
    cache_create_1h: int,
    expected: float,
) -> None:
    """Real traffic, priced by hand against the published rate card.

    These numbers are the reason the table changed: the harness reported
    $1.8052 for this batch against a true $2.4559, a 26.5% under-report
    caused entirely by billing 1-hour cache writes at the 5-minute rate.
    """
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    cost = calculate_cost(
        model,
        {
            "input": inp,
            "output": out,
            "cache_read": cache_read,
            "cache_create": 0,
            "cache_create_1h": cache_create_1h,
        },
        default_pricing(),
        on="2026-08-31",
    )
    assert cost == pytest.approx(expected, abs=0.00005)


def test_the_measured_batch_totals_the_verified_amount() -> None:
    """The whole batch, not just each row — the figure the report quoted."""
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    pricing = default_pricing()
    total = sum(
        calculate_cost(
            model,
            {
                "input": inp,
                "output": out,
                "cache_read": cache_read,
                "cache_create": 0,
                "cache_create_1h": cache_create_1h,
            },
            pricing,
            on="2026-08-31",
        )
        for _item, model, inp, out, cache_read, cache_create_1h, _expected in (MEASURED_SESSIONS)
    )
    assert total == pytest.approx(2.4559, abs=0.00005)


@pytest.mark.parametrize(
    ("model", "one_hour_rate"),
    [
        ("claude-opus-5", 10.0),
        ("claude-sonnet-5", 4.0),
        ("claude-sonnet-4-6", 6.0),
        ("claude-haiku-4-5", 2.0),
        ("claude-fable-5", 20.0),
        ("claude-fable-5-1", 20.0),
    ],
)
def test_one_hour_cache_writes_bill_at_twice_the_base_input_rate(
    model: str, one_hour_rate: float
) -> None:
    """Anthropic's multipliers: 1.25x for a 5m write, 2x for a 1h write."""
    from lazy_harness.monitoring.pricing import default_pricing

    assert default_pricing()[model]["cache_create_1h"] == one_hour_rate


def test_a_five_minute_and_a_one_hour_write_of_equal_size_differ() -> None:
    """The two buckets must reach different rates, not one shared column.

    A single flat `cache_create` rate is exactly the bug: it priced every
    write at 1.25x while 92.9% of measured write tokens were 1-hour.
    """
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    pricing = default_pricing()
    base = {"input": 0, "output": 0, "cache_read": 0}
    five_min = calculate_cost(
        "claude-sonnet-5", {**base, "cache_create": 1_000_000, "cache_create_1h": 0}, pricing
    )
    one_hour = calculate_cost(
        "claude-sonnet-5", {**base, "cache_create": 0, "cache_create_1h": 1_000_000}, pricing
    )
    assert five_min == pytest.approx(2.5)
    assert one_hour == pytest.approx(4.0)


def test_an_override_without_a_1h_rate_falls_back_to_twice_input() -> None:
    """A config override predates the 1h column and must not bill at zero.

    `load_pricing` replaces a model's whole rate dict, so an override
    written against the old four-key shape would leave 1-hour writes
    unpriced — a silent under-charge on the most expensive bucket.
    """
    from lazy_harness.monitoring.pricing import calculate_cost, load_pricing

    pricing = load_pricing(
        overrides={
            "claude-sonnet-5": {
                "input": 7.0,
                "output": 0.0,
                "cache_read": 0.0,
                "cache_create": 0.0,
            }
        }
    )
    cost = calculate_cost(
        "claude-sonnet-5",
        {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "cache_create_1h": 1_000_000},
        pricing,
    )
    assert cost == pytest.approx(14.0)


# --- billing model (ADR-050) -------------------------------------------------


def test_flat_rate_short_circuits_pricing() -> None:
    """A flat_rate row costs 0.0 with cost_source='subscription', regardless
    of whether the model even has a rate — pricing is never consulted."""
    from lazy_harness.monitoring.pricing import cost_for_billing_model, default_pricing

    tokens = {"input": 1000, "output": 500, "cache_read": 0, "cache_create": 0}
    cost, cost_source = cost_for_billing_model(
        "claude-opus-4-6", tokens, default_pricing(), billing_model="flat_rate"
    )
    assert cost == 0.0
    assert cost_source == "subscription"


def test_flat_rate_short_circuits_even_for_an_unpriced_model() -> None:
    from lazy_harness.monitoring.pricing import cost_for_billing_model, default_pricing

    tokens = {"input": 1000, "output": 500, "cache_read": 0, "cache_create": 0}
    cost, cost_source = cost_for_billing_model(
        "some-model-with-no-rate", tokens, default_pricing(), billing_model="flat_rate"
    )
    assert cost == 0.0
    assert cost_source == "subscription"


def test_per_token_priced_row_carries_pricing_cost_source() -> None:
    from lazy_harness.monitoring.pricing import cost_for_billing_model, default_pricing

    tokens = {"input": 1000, "output": 500, "cache_read": 0, "cache_create": 0}
    cost, cost_source = cost_for_billing_model(
        "claude-opus-4-6", tokens, default_pricing(), billing_model="per_token"
    )
    assert cost > 0.0
    assert cost_source == "pricing"


def test_per_token_unpriced_row_carries_no_cost_source() -> None:
    """A per_token row with no rate still costs 0.0, but cost_source stays
    None — the unpriced gap this dimension exists to surface."""
    from lazy_harness.monitoring.pricing import cost_for_billing_model, default_pricing

    tokens = {"input": 1000, "output": 500, "cache_read": 0, "cache_create": 0}
    cost, cost_source = cost_for_billing_model(
        "unknown-model", tokens, default_pricing(), billing_model="per_token"
    )
    assert cost == 0.0
    assert cost_source is None


# --- flat-rate agents and the Codex model name (ADR-050 x ADR-053) ---------
#
# `gpt-5-codex` is the model string the Codex reader's `turn_context` line
# declares (measured 2026-09-17 in tests/unit/test_agent_codex_transcript.py
# and tests/unit/test_ingest.py:951, on live Codex CLI rollouts). It carries
# no DEFAULT_PRICING entry, deliberately: the current authoritative source
# (https://developers.openai.com/api/docs/pricing, checked 2026-09-17) lists
# only `gpt-5.3-codex` in its "Specialized models" table — a different,
# newer model id — so there is nothing to cite `gpt-5-codex`'s own rate
# against. Mapping one id's price onto the other would be a guess wearing a
# citation, exactly what this table's own convention (a public source URL
# and date beside every rate) exists to rule out. The two rows below are the
# registered expected behaviour in its place: a flat-rate Codex session
# never turns this gap into a false "unpriced" alarm, and a per-token one
# still surfaces it by name.


def test_gpt_5_codex_has_no_default_rate() -> None:
    """No entry exists for the model the Codex reader actually emits.

    Documented absence, not an oversight: see the module comment above this
    test for why no rate is citable yet.
    """
    from lazy_harness.monitoring.pricing import default_pricing

    assert "gpt-5-codex" not in default_pricing()


def test_a_flat_rate_codex_session_never_becomes_an_unpriced_gap() -> None:
    """billing_model='flat_rate' short-circuits pricing regardless of the
    model — a ChatGPT-plan Codex profile's real usage must not read as a
    pricing hole just because its model has no per-token rate."""
    from lazy_harness.monitoring.pricing import cost_for_billing_model, default_pricing

    tokens = {"input": 29_400, "output": 7, "cache_read": 0, "cache_create": 0}
    cost, cost_source = cost_for_billing_model(
        "gpt-5-codex", tokens, default_pricing(), billing_model="flat_rate"
    )
    assert cost == 0.0
    assert cost_source == "subscription"


@pytest.mark.parametrize(
    ("model", "billing_model"),
    [
        ("claude-opus-4-6", "per_token"),
        ("gpt-5-codex", "flat_rate"),
    ],
)
def test_a_named_cost_source_is_always_a_cost_sources_member(
    model: str, billing_model: str
) -> None:
    """Whenever `cost_for_billing_model` names a source at all, it is one of
    the two ADR-050 enum members — never a third spelling drifting in."""
    from lazy_harness.monitoring.pricing import (
        COST_SOURCES,
        cost_for_billing_model,
        default_pricing,
    )

    tokens = {"input": 1000, "output": 500, "cache_read": 0, "cache_create": 0}
    _cost, cost_source = cost_for_billing_model(
        model, tokens, default_pricing(), billing_model=billing_model
    )
    assert cost_source in COST_SOURCES


def test_a_per_token_codex_session_with_an_unrated_model_is_an_unpriced_gap() -> None:
    """billing_model='per_token' against the same unrated model is the one
    case cost_source exists to name: an API-key Codex profile with no rate
    for gpt-5-codex must surface in `unknown_models`, not render as $0.00."""
    from lazy_harness.monitoring.pricing import cost_for_billing_model, default_pricing

    tokens = {"input": 29_400, "output": 7, "cache_read": 0, "cache_create": 0}
    cost, cost_source = cost_for_billing_model(
        "gpt-5-codex", tokens, default_pricing(), billing_model="per_token"
    )
    assert cost == 0.0
    assert cost_source is None
