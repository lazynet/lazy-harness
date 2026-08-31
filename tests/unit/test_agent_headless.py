"""Headless invocation seam — argv construction and envelope normalisation.

These tests pin the contract a non-Claude adapter would have to satisfy, so
the assertions are about the *normalised* result, never about Claude Code's
own field names (except where the fixture supplies them as input).
"""

from __future__ import annotations

import json

import pytest


def _claude_envelope(**overrides) -> str:
    """A realistic Claude Code `--output-format json` envelope."""
    data = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 2100,
        "duration_api_ms": 1749,
        "num_turns": 1,
        "result": "OK",
        "total_cost_usd": 0.061971,
        "usage": {
            "input_tokens": 9,
            "cache_creation_input_tokens": 30876,
            "cache_read_input_tokens": 0,
            "output_tokens": 42,
        },
    }
    data.update(overrides)
    return json.dumps(data)


# --- parse_headless_result -------------------------------------------------


def test_parse_maps_envelope_onto_normalised_fields() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result(_claude_envelope(), 0)

    assert result.success is True
    assert result.output == "OK"
    assert result.exit_code == 0
    assert result.cost_usd == pytest.approx(0.061971)
    assert result.num_turns == 1


def test_parse_prefers_wall_clock_duration_over_api_duration() -> None:
    """`duration_api_ms` is the API leg only; the envelope carries both."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result(_claude_envelope(), 0)

    assert result.duration_ms == 2100


def test_parse_sums_the_three_input_token_fields() -> None:
    """`input_tokens` is the uncached slice of the last turn, not the input."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result(_claude_envelope(), 0)

    assert result.prompt_tokens == 9 + 30876 + 0
    assert result.output_tokens == 42


def test_parse_keeps_cache_fields_separate() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result(_claude_envelope(), 0)

    assert result.cache_creation_tokens == 30876
    assert result.cache_read_tokens == 0


def test_parse_reports_absent_usage_as_none_not_zero() -> None:
    """A zero would enter a cost report as a fact. Absence must stay absence."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    envelope = json.dumps({"result": "hi", "is_error": False})
    result = ClaudeCodeAdapter().parse_headless_result(envelope, 0)

    assert result.prompt_tokens is None
    assert result.output_tokens is None
    assert result.cache_creation_tokens is None
    assert result.cache_read_tokens is None
    assert result.cost_usd is None
    assert result.duration_ms is None
    assert result.num_turns is None


def test_parse_keeps_a_reported_zero_as_zero() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    envelope = json.dumps(
        {
            "result": "hi",
            "usage": {
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 512,
                "output_tokens": 0,
            },
        }
    )
    result = ClaudeCodeAdapter().parse_headless_result(envelope, 0)

    assert result.cache_creation_tokens == 0
    assert result.output_tokens == 0
    assert result.prompt_tokens == 512


def test_parse_falls_back_to_raw_stdout_when_not_json() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result("boom: not json", 1)

    assert result.success is False
    assert result.output == "boom: not json"
    assert result.raw is None
    assert result.prompt_tokens is None


@pytest.mark.parametrize("payload", ["null", "42", '["a"]', '"a string"'])
def test_parse_survives_valid_json_of_the_wrong_type(payload: str) -> None:
    """Valid JSON that is not an object must not reach `.get()`."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result(payload, 0)

    assert result.output == payload
    assert result.raw is None


def test_parse_marks_failure_on_nonzero_exit_even_with_a_valid_envelope() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result(_claude_envelope(), 1)

    assert result.success is False
    assert result.exit_code == 1
    assert result.output == "OK"


def test_parse_marks_failure_when_the_envelope_flags_an_error() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    envelope = _claude_envelope(is_error=True, subtype="error_during_execution")
    result = ClaudeCodeAdapter().parse_headless_result(envelope, 0)

    assert result.success is False


def test_parse_exposes_the_provider_envelope_as_raw() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result(_claude_envelope(), 0)

    assert result.raw is not None
    assert result.raw["duration_api_ms"] == 1749


# --- resolve_model ---------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "expected"),
    [("fast", "haiku"), ("balanced", "sonnet"), ("deep", "opus")],
)
def test_resolve_model_maps_tiers_to_provider_aliases(tier: str, expected: str) -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().resolve_model(tier=tier, explicit=None) == expected


def test_resolve_model_passes_an_explicit_id_through_untouched() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    resolved = ClaudeCodeAdapter().resolve_model(tier=None, explicit="claude-opus-4-1-20250805")

    assert resolved == "claude-opus-4-1-20250805"


def test_resolve_model_lets_an_explicit_id_win_over_a_tier() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().resolve_model(tier="fast", explicit="opus") == "opus"


def test_resolve_model_returns_none_when_neither_is_given() -> None:
    """No `--model` flag at all — the provider picks its own default."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().resolve_model(tier=None, explicit=None) is None


def test_resolve_model_rejects_an_unknown_tier() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    with pytest.raises(ValueError, match="turbo"):
        ClaudeCodeAdapter().resolve_model(tier="turbo", explicit=None)


# --- headless_argv ---------------------------------------------------------


def test_headless_argv_asks_for_print_mode_and_json() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    argv = ClaudeCodeAdapter().headless_argv(model=None, allowed_tools=None)

    assert argv == ["-p", "--output-format", "json"]


def test_headless_argv_omits_the_model_flag_when_no_model_is_resolved() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    argv = ClaudeCodeAdapter().headless_argv(model=None, allowed_tools=None)

    assert "--model" not in argv


def test_headless_argv_carries_no_prompt() -> None:
    """The prompt travels on stdin: argv is bounded, ARG_MAX is not."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    argv = ClaudeCodeAdapter().headless_argv(model="haiku", allowed_tools=["Read"])

    assert all(not a.startswith("Reply") for a in argv)
    assert len(" ".join(argv)) < 200


def test_headless_argv_adds_the_model_when_resolved() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    argv = ClaudeCodeAdapter().headless_argv(model="haiku", allowed_tools=None)

    assert argv[argv.index("--model") + 1] == "haiku"


def test_headless_argv_allows_a_named_tool_list() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    argv = ClaudeCodeAdapter().headless_argv(model=None, allowed_tools=["Read", "Write"])

    assert argv[argv.index("--allowedTools") + 1] == "Read,Write"
    assert "--disallowedTools" not in argv


def test_headless_argv_denies_tools_by_name_for_the_empty_list() -> None:
    """`--allowedTools ''` is a no-op: the CLI still grants its default reads."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    argv = ClaudeCodeAdapter().headless_argv(model=None, allowed_tools=[])

    denied = argv[argv.index("--disallowedTools") + 1].split(",")
    assert {"Task", "Bash", "Read", "Write", "NotebookEdit", "TodoWrite"} <= set(denied)
    assert "--allowedTools" not in argv


def test_headless_argv_leaves_tool_policy_to_the_provider_for_none() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    argv = ClaudeCodeAdapter().headless_argv(model=None, allowed_tools=None)

    assert "--allowedTools" not in argv
    assert "--disallowedTools" not in argv


# --- protocol conformance --------------------------------------------------


def test_claude_adapter_satisfies_the_headless_protocol() -> None:
    from lazy_harness.agents.base import HeadlessAgent
    from lazy_harness.agents.registry import get_agent

    assert isinstance(get_agent("claude-code"), HeadlessAgent)


def test_null_adapter_does_not_claim_headless_support() -> None:
    """`lh exec` refuses rather than exec'ing an agent that cannot be parsed."""
    from lazy_harness.agents.base import HeadlessAgent
    from lazy_harness.agents.registry import get_agent

    assert not isinstance(get_agent("null"), HeadlessAgent)


def test_headless_tiers_are_declared_in_one_place() -> None:
    """The CLI and the adapters must not keep separate tier vocabularies."""
    from lazy_harness.agents.base import HEADLESS_TIERS

    assert HEADLESS_TIERS == ("fast", "balanced", "deep")


# --- session pinning (ADR-037 D5) ------------------------------------------


def test_parse_surfaces_the_session_id_from_the_envelope() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result(
        _claude_envelope(session_id="925529e2-211b-4f64-b2a2-90a4f57b23c9"), 0
    )
    assert result.session_id == "925529e2-211b-4f64-b2a2-90a4f57b23c9"


def test_parse_leaves_session_id_none_when_the_envelope_omits_it() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result(_claude_envelope(), 0)
    assert result.session_id is None


def test_parse_leaves_session_id_none_on_unparseable_stdout() -> None:
    """The measured shape of a refused session id: exit 1, empty stdout."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result("", 1)
    assert result.session_id is None
    assert result.success is False


def test_parse_ignores_a_non_string_session_id() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().parse_headless_result(_claude_envelope(session_id=42), 0)
    assert result.session_id is None


def test_claude_session_argv_pins_the_session_id() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().session_argv("abc-123") == ["--session-id", "abc-123"]


def test_claude_adapter_satisfies_the_session_pinning_protocol() -> None:
    from lazy_harness.agents.base import SessionPinningAgent
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert isinstance(ClaudeCodeAdapter(), SessionPinningAgent)


def test_an_adapter_without_session_argv_is_not_a_session_pinning_agent() -> None:
    """Pinning is a capability, not a requirement: `lh exec` degrades instead.

    Adding the method to `HeadlessAgent` itself would have made every
    third-party adapter fail `isinstance` and be refused outright.
    """
    from lazy_harness.agents.base import HeadlessAgent, SessionPinningAgent

    class _NoPinning:
        def resolve_model(self, *, tier: str | None, explicit: str | None) -> str | None:
            return explicit

        def headless_argv(
            self, *, model: str | None, allowed_tools: list[str] | None
        ) -> list[str]:
            return []

        def parse_headless_result(self, stdout: str, exit_code: int):  # noqa: ANN201
            raise NotImplementedError

    adapter = _NoPinning()
    assert isinstance(adapter, HeadlessAgent), "must still be usable headlessly"
    assert not isinstance(adapter, SessionPinningAgent)
