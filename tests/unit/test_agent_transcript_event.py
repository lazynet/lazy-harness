"""The shape `TranscriptEvent` and `TokenUsage` promise across the Protocol boundary.

ADR-053 widens both so a metering consumer can read an agent's transcript
through its own reader. The widening is *append with defaults* — ADR-037's
mechanism for `MetricEvent` — and that property is what these assert: a reader
written before the fields existed stays valid, and every new field arrives
absent rather than zero, for the reason `TokenUsage`'s own docstring gives.
"""

from __future__ import annotations

from lazy_harness.agents.base import Signal, TokenUsage, TranscriptEvent


def test_a_usage_event_carries_the_model_that_produced_the_turn() -> None:
    event = TranscriptEvent(signal=Signal.TOKEN_USAGE, model="claude-opus-4-6")

    assert event.model == "claude-opus-4-6"


def test_a_usage_event_carries_the_provider_s_own_id_for_the_turn() -> None:
    """Distinct from `tool_use_id`, which pairs a call with its result."""
    event = TranscriptEvent(signal=Signal.TOKEN_USAGE, message_id="msg_a", tool_use_id=None)

    assert (event.message_id, event.tool_use_id) == ("msg_a", None)


def test_token_usage_carries_the_one_hour_cache_write_separately() -> None:
    """5-minute and 1-hour writes are priced differently; one field cannot say both."""
    usage = TokenUsage(cache_creation_tokens=60, cache_creation_1h_tokens=30)

    assert (usage.cache_creation_tokens, usage.cache_creation_1h_tokens) == (60, 30)


def test_a_reader_written_before_the_widening_still_constructs() -> None:
    """The append-with-defaults property: no existing call site gains a required argument."""
    event = TranscriptEvent(signal=Signal.MESSAGES, role="assistant", text="hi")

    assert (event.model, event.message_id) == (None, None)


def test_the_new_token_field_is_absent_and_not_zero_when_unreported() -> None:
    """A provider with no TTL split and a turn that wrote no 1h cache are different facts."""
    usage = TokenUsage(input_tokens=11)

    assert usage.cache_creation_1h_tokens is None
