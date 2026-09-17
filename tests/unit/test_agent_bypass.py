"""The bypass axis — three declared positions, and what each adapter answers.

`lh run` is an argv passthrough today, so `lcca` ships a Claude Code flag to
whatever binary the profile resolves. The point of `Bypass` is that the axis has
three positions rather than one, and that an agent without a position **says so**
instead of being handed a neighbouring flag that its parser may or may not
reject.

The rule every test below circles: `None` is an answer, never a fallback. An
agent with no sandbox has no `NO_SANDBOX`; that is a reported state, and the one
thing it must never silently become is `ACTIVATE`.
"""

from __future__ import annotations

import pytest

from lazy_harness.agents.base import Bypass, BypassUnsupportedError, bypass_argv_or_raise
from lazy_harness.agents.registry import get_agent


def test_the_axis_has_exactly_three_declared_positions() -> None:
    """A fourth would have to be declared here before an adapter could answer it,
    which is the property that keeps this from drifting into an argv translator."""
    assert [level.value for level in Bypass] == ["enable", "activate", "no_sandbox"]


def test_no_sandbox_is_spelled_with_an_underscore_in_the_enum() -> None:
    """The CLI spells it `no-sandbox`; the enum member is `no_sandbox`, and
    `run_cmd` converts. Pinning both halves keeps the conversion honest."""
    assert Bypass("no_sandbox") is Bypass.NO_SANDBOX


# --- Claude Code: the two flags `lcca` is being migrated off ----------------
#
# Verified against `claude --help` on this machine. The ENABLE row is the one
# that matters for the migration: `--allow-dangerously-skip-permissions` is
# documented as "Enable bypassing all permission checks **as an option, without
# it being enabled by default**", which is exactly what ENABLE means and exactly
# what `lcca` means today.


def test_claude_enable_is_the_flag_lcca_ships_today() -> None:
    adapter = get_agent("claude-code")
    assert adapter.bypass_argv(Bypass.ENABLE) == ["--allow-dangerously-skip-permissions"]


def test_claude_activate_is_the_flag_that_turns_it_on() -> None:
    adapter = get_agent("claude-code")
    assert adapter.bypass_argv(Bypass.ACTIVATE) == ["--dangerously-skip-permissions"]


def test_claude_has_no_no_sandbox_level() -> None:
    """Claude Code exposes no OS-sandbox flag on its argv. Returning the
    ACTIVATE flag here would be the exact failure the axis exists to prevent:
    a request to remove the sandbox answered by removing the prompts."""
    adapter = get_agent("claude-code")
    assert adapter.bypass_argv(Bypass.NO_SANDBOX) is None


# --- Codex: provisional, from help text alone ------------------------------


def test_codex_has_no_enable_position() -> None:
    """0.154.0 has no flag meaning "available but off": the approval-policy
    settings turn approvals off, they do not make an off switch reachable."""
    adapter = get_agent("codex")
    assert adapter.bypass_argv(Bypass.ENABLE) is None


def test_codex_activate_drops_approvals_and_keeps_the_sandbox() -> None:
    adapter = get_agent("codex")
    assert adapter.bypass_argv(Bypass.ACTIVATE) == ["--ask-for-approval", "never"]


def test_codex_no_sandbox_is_the_single_combined_flag() -> None:
    adapter = get_agent("codex")
    assert adapter.bypass_argv(Bypass.NO_SANDBOX) == ["--dangerously-bypass-approvals-and-sandbox"]


def test_codex_never_emits_the_hook_trust_flag() -> None:
    """`--dangerously-bypass-hook-trust` is on the same help page and is a
    different axis — whether hooks run without persisted trust, not whether the
    model needs approval. Sweeping it in here would make `--bypass` quietly
    disable the harness's own guardrails."""
    adapter = get_agent("codex")
    for level in Bypass:
        assert "--dangerously-bypass-hook-trust" not in (adapter.bypass_argv(level) or [])


# --- Copilot: nothing is measured, so nothing is claimed --------------------


@pytest.mark.parametrize("level", list(Bypass))
def test_copilot_declares_no_bypass_level_at_all(level: Bypass) -> None:
    """ADR-047 ships only `run`/`log`-backed rows for this adapter. No probe has
    measured a bypass flag, so every level is `None` — an unmeasured flag
    forwarded to a binary is the thing the evidence discipline exists to stop."""
    adapter = get_agent("copilot")
    assert adapter.bypass_argv(level) is None


# --- the sentinel, and the refusal every caller goes through ----------------


@pytest.mark.parametrize("level", list(Bypass))
def test_the_null_adapter_supports_no_level(level: Bypass) -> None:
    assert get_agent("null").bypass_argv(level) is None


@pytest.mark.parametrize("level", list(Bypass))
def test_the_refusal_names_the_agent_and_the_level_it_refused(level: Bypass) -> None:
    """Exercised through the shipped sentinel rather than a fake, and asserted
    on the structured attributes rather than the message text: the CLI renders
    the message, and a test that pins only the prose cannot tell a correct
    refusal from one that names the wrong level."""
    adapter = get_agent("null")

    with pytest.raises(BypassUnsupportedError) as caught:
        bypass_argv_or_raise(adapter, level)

    assert caught.value.agent == "null"
    assert caught.value.level is level
    assert "null" in str(caught.value)
    assert level.value.replace("_", "-") in str(caught.value)


def test_the_helper_returns_the_flags_when_the_level_is_supported() -> None:
    """The success path through the same call site, so the raise cannot be
    unconditional."""
    adapter = get_agent("claude-code")
    assert bypass_argv_or_raise(adapter, Bypass.ENABLE) == ["--allow-dangerously-skip-permissions"]


def test_claude_no_sandbox_refuses_through_the_same_helper() -> None:
    """The second half of the error path the brief names: a real adapter that
    supports two levels and not the third."""
    adapter = get_agent("claude-code")

    with pytest.raises(BypassUnsupportedError) as caught:
        bypass_argv_or_raise(adapter, Bypass.NO_SANDBOX)

    assert caught.value.agent == "claude-code"
    assert caught.value.level is Bypass.NO_SANDBOX


@pytest.mark.parametrize("agent_type", ["claude-code", "codex", "copilot", "null"])
@pytest.mark.parametrize("level", list(Bypass))
def test_every_adapter_answers_every_level_without_raising(agent_type: str, level: Bypass) -> None:
    """`bypass_argv` is a declaration, not an attempt: an adapter that raised
    for an unsupported level would make the CLI's error path depend on which
    agent it happened to be talking to."""
    result = get_agent(agent_type).bypass_argv(level)
    assert result is None or (isinstance(result, list) and all(isinstance(f, str) for f in result))
