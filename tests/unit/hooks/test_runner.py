"""The runner: stdin -> adapter -> builtin -> adapter -> three channels.

The failure policy is the point of these tests. `cli/hooks_cmd.py` ends every
path in `sys.exit(0)`, which on a blocking hook means a hook that cannot run
approves the tool call. The runner refuses instead, and only for the hooks
declared blocking -- an informational hook that dies must not stop the agent.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from lazy_harness.agents.base import HookDecision, HookEvent, Verdict
from lazy_harness.hooks import runner
from lazy_harness.hooks.loader import _BUILTIN_HOOKS, BuiltinHookSpec

PRE_TOOL_USE = {
    "hook_event_name": "PreToolUse",
    "session_id": "s1",
    "cwd": "/tmp",
    "transcript_path": "/tmp/t.jsonl",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf /"},
}

# The keys that tell the two callers apart, each as measured rather than
# assumed. Claude Code 2.1.281 sends `prompt_id` on PreToolUse and no
# `turn_id` or `model` (dump-hook probe, 2026-09-24). Codex 0.154.0 sends
# `turn_id` and `model` and no `prompt_id` (`specs/designs/codex-evidence.md`
# §1 and probe 5).
CLAUDE_PRE_TOOL_USE = {
    **PRE_TOOL_USE,
    "permission_mode": "default",
    "prompt_id": "p1",
    "tool_use_id": "u1",
}
CODEX_PRE_TOOL_USE = {
    **PRE_TOOL_USE,
    "permission_mode": "bypassPermissions",
    "turn_id": "01a0a301-0db8-70a2-89b7-7d55840aeba3",
    "model": "gpt-6-astra",
    "tool_use_id": "u1",
}


def register(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    main: object,
    *,
    blocking: bool = False,
    event: str | None = None,
) -> None:
    """Register a builtin backed by a module built for this test."""
    module_name = f"lazy_harness_test_builtin_{name.replace('-', '_')}"
    module = types.ModuleType(module_name)
    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setitem(
        _BUILTIN_HOOKS,
        name,
        BuiltinHookSpec(module=module_name, blocking=blocking, event=event),
    )


def test_decision_is_serialised_by_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    register(
        monkeypatch,
        "guard",
        lambda event: HookDecision(verdict=Verdict.DENY, reason="no"),
        blocking=True,
    )

    result = runner.run_hook("guard", profile="lazy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 2
    assert result.stderr == "no"
    assert json.loads(result.stdout or "{}") == {}


def test_the_builtin_receives_the_parsed_event(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[HookEvent] = []

    def main(event: HookEvent) -> HookDecision:
        seen.append(event)
        return HookDecision()

    register(monkeypatch, "spy", main, blocking=False)

    runner.run_hook("spy", profile="lazy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert len(seen) == 1
    assert seen[0].event == "pre_tool_use"
    assert seen[0].profile == "lazy"
    assert seen[0].tool is not None
    assert seen[0].tool.command == "rm -rf /"


def test_abstention_emits_no_permission_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    register(monkeypatch, "quiet", lambda event: HookDecision(), blocking=True)

    result = runner.run_hook("quiet", profile="lazy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0
    assert result.stdout is None
    assert result.stderr == ""


#: The four shapes of "the runner has no payload it can use": nothing on stdin,
#: nothing but whitespace, bytes that are not JSON, and JSON that parses into
#: something other than an object. One class, one policy row.
UNUSABLE_PAYLOADS = ["", "   \n", "not json at all", "[]", "null", "42", '"a string"']


@pytest.mark.parametrize("stdin_text", UNUSABLE_PAYLOADS)
def test_unparseable_payload_refuses_for_a_blocking_hook(
    monkeypatch: pytest.MonkeyPatch, stdin_text: str
) -> None:
    """Decision 3's table, row "Unparseable payload": exit 2, reason on stderr.

    A blocking hook exists to be consulted before a tool call. Handing it an
    empty event and exiting 0 is indistinguishable, on the wire, from the guard
    having looked and found nothing to object to -- which is the failure mode
    the whole design exists to make visible.
    """
    seen: list[HookEvent] = []

    def main(event: HookEvent) -> HookDecision:
        seen.append(event)
        return HookDecision()

    register(monkeypatch, "guard", main, blocking=True, event="pre_tool_use")

    result = runner.run_hook("guard", profile="lazy", stdin_text=stdin_text)

    assert result.exit_code == 2
    assert "payload" in result.stderr
    assert result.stdout is None
    assert seen == [], "the builtin must not run on a payload the runner cannot read"


@pytest.mark.parametrize("stdin_text", UNUSABLE_PAYLOADS)
def test_unparseable_payload_lets_an_informational_hook_through(
    monkeypatch: pytest.MonkeyPatch, stdin_text: str
) -> None:
    """Same row, informational column: exit 0, warning on stderr, no stdout.

    The hook did not run, so it has nothing to say on stdout -- and an agent
    that reads stdout as the hook's output must not be handed a partial one.
    """
    register(monkeypatch, "notes", lambda event: HookDecision(), blocking=False)

    result = runner.run_hook("notes", profile="lazy", stdin_text=stdin_text)

    assert result.exit_code == 0
    assert "payload" in result.stderr
    assert result.stdout is None


def test_a_payload_with_no_event_falls_back_to_the_declared_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`lh hook <name>` carries no event flag, so the registry has to answer."""
    seen: list[HookEvent] = []

    def main(event: HookEvent) -> HookDecision:
        seen.append(event)
        return HookDecision()

    register(monkeypatch, "wired", main, event="session_start")

    result = runner.run_hook("wired", profile="lazy", stdin_text=json.dumps({"session_id": "s1"}))

    assert result.exit_code == 0
    assert seen[0].event == "session_start"


def test_a_declared_event_does_not_override_one_the_payload_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback fills an absence; it must not paper over a wrong name."""
    register(monkeypatch, "notes", lambda event: HookDecision(), event="session_start")
    payload = dict(PRE_TOOL_USE, hook_event_name="NotAnEvent")

    result = runner.run_hook("notes", profile="lazy", stdin_text=json.dumps(payload))

    assert result.exit_code == 0
    assert "NotAnEvent" in result.stderr


def test_a_raising_blocking_builtin_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(event: HookEvent) -> HookDecision:
        raise RuntimeError("kaboom")

    register(monkeypatch, "guard", boom, blocking=True)

    result = runner.run_hook("guard", profile="lazy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 2
    assert "kaboom" in result.stderr


def test_a_raising_informational_builtin_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(event: HookEvent) -> HookDecision:
        raise RuntimeError("kaboom")

    register(monkeypatch, "notes", boom, blocking=False)

    result = runner.run_hook("notes", profile="lazy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0
    assert "kaboom" in result.stderr


def test_an_unknown_hook_name_refuses_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    result = runner.run_hook("nope", profile="lazy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0
    assert "nope" in result.stderr


def test_a_builtin_without_main_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    module_name = "lazy_harness_test_builtin_no_main"
    monkeypatch.setitem(sys.modules, module_name, types.ModuleType(module_name))
    monkeypatch.setitem(
        _BUILTIN_HOOKS, "headless", BuiltinHookSpec(module=module_name, blocking=False)
    )

    result = runner.run_hook("headless", profile="lazy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0
    assert "main" in result.stderr


def test_an_unknown_native_event_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    register(monkeypatch, "notes", lambda event: HookDecision(), blocking=False)
    payload = dict(PRE_TOOL_USE, hook_event_name="NotAnEvent")

    result = runner.run_hook("notes", profile="lazy", stdin_text=json.dumps(payload))

    assert result.exit_code == 0
    assert "NotAnEvent" in result.stderr


@pytest.fixture
def configured_profiles(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A config declaring two profiles, so 'unknown profile' is a real state."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "lazy"\n\n'
        f'[profiles.lazy]\nconfig_dir = "{tmp_path / "lazy"}"\nroots = ["~"]\n\n'
        f'[profiles.flex]\nconfig_dir = "{tmp_path / "flex"}"\nroots = ["~"]\n'
    )
    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: cfg)


def test_unknown_profile_falls_back_to_default_for_a_benign_command(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None
) -> None:
    """A blocking hook that abstains must still abstain under the fallback.

    Before this fix, `_adapter_for` raised before the builtin ever ran, so
    every blocking hook exited 2 on an unknown profile regardless of what the
    command was -- `ls` and `rm -rf /` got the same diagnostic.
    """
    register(monkeypatch, "guard", lambda event: HookDecision(), blocking=True)

    result = runner.run_hook("guard", profile="ghost", stdin_text=json.dumps(CLAUDE_PRE_TOOL_USE))

    assert result.exit_code == 0
    assert "ghost" in result.stderr
    assert "lazy" in result.stderr


def test_unknown_profile_still_blocks_a_dangerous_command(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None
) -> None:
    """The fallback resolves the adapter, not the verdict: a real block still fires."""
    register(
        monkeypatch,
        "guard",
        lambda event: HookDecision(verdict=Verdict.DENY, reason="blocked"),
        blocking=True,
    )

    result = runner.run_hook("guard", profile="ghost", stdin_text=json.dumps(CLAUDE_PRE_TOOL_USE))

    assert result.exit_code == 2
    assert "blocked" in result.stderr
    assert "ghost" in result.stderr
    assert "lazy" in result.stderr


def test_unknown_profile_lets_an_informational_hook_through(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None
) -> None:
    register(monkeypatch, "notes", lambda event: HookDecision(), blocking=False)

    result = runner.run_hook("notes", profile="ghost", stdin_text=json.dumps(CLAUDE_PRE_TOOL_USE))

    assert result.exit_code == 0
    assert "ghost" in result.stderr
    assert "lazy" in result.stderr


def test_unknown_profile_resolves_the_default_s_adapter(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None
) -> None:
    """The event the builtin sees is threaded through under the default profile,
    not the unresolved name -- so memory scope and metrics land on a profile
    that actually exists."""
    seen: list[HookEvent] = []

    def main(event: HookEvent) -> HookDecision:
        seen.append(event)
        return HookDecision()

    register(monkeypatch, "spy", main, blocking=False)

    runner.run_hook("spy", profile="ghost", stdin_text=json.dumps(CLAUDE_PRE_TOOL_USE))

    assert len(seen) == 1
    assert seen[0].profile == "lazy"


def test_a_declared_profile_runs(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None
) -> None:
    register(monkeypatch, "notes", lambda event: HookDecision(system_message="hi"), blocking=False)

    result = runner.run_hook("notes", profile="flex", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0
    assert json.loads(result.stdout or "{}") == {"systemMessage": "hi"}


def test_an_unresolved_profile_falls_back_to_the_configured_agent(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None
) -> None:
    """`profile_name()` returns "" whenever it cannot match a config dir.

    That is reachable on a machine with profiles declared -- no
    `CLAUDE_CONFIG_DIR`, or one pointing somewhere the table does not name --
    and refusing there would take every hook down with it, which is the same
    reasoning `_adapter_for` already applies to an empty table.
    """
    register(monkeypatch, "guard", lambda event: HookDecision(system_message="ran"), blocking=True)

    result = runner.run_hook("guard", profile="", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0
    assert result.stderr == ""
    assert json.loads(result.stdout or "{}") == {"systemMessage": "ran"}


@pytest.fixture
def profiles_without_a_resolvable_default(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two declared profiles whose configured default names a third that does
    not exist -- the case decision (b) still must fail closed on."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "gone"\n\n'
        f'[profiles.lazy]\nconfig_dir = "{tmp_path / "lazy"}"\nroots = ["~"]\n\n'
        f'[profiles.flex]\nconfig_dir = "{tmp_path / "flex"}"\nroots = ["~"]\n'
    )
    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: cfg)


def test_no_resolvable_default_still_refuses_for_a_blocking_hook(
    monkeypatch: pytest.MonkeyPatch, profiles_without_a_resolvable_default: None
) -> None:
    """A benign command must not slip through just because a default was
    configured -- the fallback only helps when that default actually exists."""
    register(monkeypatch, "guard", lambda event: HookDecision(), blocking=True)

    result = runner.run_hook("guard", profile="ghost", stdin_text=json.dumps(CLAUDE_PRE_TOOL_USE))

    assert result.exit_code == 2
    assert "ghost" in result.stderr
    assert "no default" in result.stderr.lower()


def test_no_resolvable_default_lets_an_informational_hook_through(
    monkeypatch: pytest.MonkeyPatch, profiles_without_a_resolvable_default: None
) -> None:
    register(monkeypatch, "notes", lambda event: HookDecision(), blocking=False)

    result = runner.run_hook("notes", profile="ghost", stdin_text=json.dumps(CLAUDE_PRE_TOOL_USE))

    assert result.exit_code == 0
    assert "ghost" in result.stderr


@pytest.fixture
def codex_profile(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A config whose global agent and one profile's agent disagree.

    The disagreement is the point: a profile that inherits the global agent
    cannot tell a runner that resolves per profile from one that resolves
    globally.
    """
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "lazy"\n\n'
        f'[profiles.lazy]\nconfig_dir = "{tmp_path / "lazy"}"\nroots = ["~"]\n\n'
        f'[profiles.gate]\nconfig_dir = "{tmp_path / "gate"}"\nroots = ["~"]\n'
        'agent = "codex"\n'
    )
    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: cfg)
    return "gate"


def test_a_profile_declaring_an_agent_gets_that_agent_s_wire_format(
    monkeypatch: pytest.MonkeyPatch, codex_profile: str
) -> None:
    """The runner resolved `[agent].type` while deploy resolved the profile's.

    Measured by the step 4 contract gate: under `[profiles.gate] agent = "codex"`
    the runner emitted Claude Code's refusal — a top-level `systemMessage` and
    exit 2 — into a config dir deploy had written in Codex's shape. Both are
    channels `CodexAdapter.format_hook_output` documents it never uses.
    """
    register(
        monkeypatch,
        "guard",
        lambda event: HookDecision(verdict=Verdict.DENY, reason="no"),
        blocking=True,
    )

    result = runner.run_hook("guard", profile=codex_profile, stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0, "a Codex profile's deny is the envelope on exit 0"
    body = json.loads(result.stdout or "{}")
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "systemMessage" not in body


def test_a_profile_inheriting_the_global_agent_still_gets_it(
    monkeypatch: pytest.MonkeyPatch, codex_profile: str
) -> None:
    """The guard on the fix: per-profile resolution must not drop the fallback."""
    register(
        monkeypatch,
        "guard",
        lambda event: HookDecision(verdict=Verdict.DENY, reason="no"),
        blocking=True,
    )

    result = runner.run_hook("guard", profile="lazy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 2
    assert result.stderr == "no"


def _deny(monkeypatch: pytest.MonkeyPatch) -> None:
    register(
        monkeypatch,
        "guard",
        lambda event: HookDecision(verdict=Verdict.DENY, reason="blocked"),
        blocking=True,
    )


def test_a_codex_caller_on_an_unknown_profile_is_blocked_in_codex_s_format(
    monkeypatch: pytest.MonkeyPatch, codex_profile: str
) -> None:
    """The fallback must never change the wire format the caller speaks.

    The default here is a Claude Code profile. Falling back to it answered a
    Codex session in Claude Code's format and under Claude Code's profile. The
    one declared Codex profile is the only fallback that keeps Codex's envelope.
    """
    _deny(monkeypatch)

    result = runner.run_hook("guard", profile="ghost", stdin_text=json.dumps(CODEX_PRE_TOOL_USE))

    assert result.exit_code == 0, "a Codex profile's deny is the envelope on exit 0"
    body = json.loads(result.stdout or "{}")
    assert body["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "ghost" in result.stderr
    assert codex_profile in result.stderr


def test_a_codex_caller_runs_under_the_codex_profile_it_fell_back_to(
    monkeypatch: pytest.MonkeyPatch, codex_profile: str
) -> None:
    seen: list[HookEvent] = []

    def main(event: HookEvent) -> HookDecision:
        seen.append(event)
        return HookDecision()

    register(monkeypatch, "spy", main, blocking=False)

    runner.run_hook("spy", profile="ghost", stdin_text=json.dumps(CODEX_PRE_TOOL_USE))

    assert [event.profile for event in seen] == [codex_profile]


def test_a_claude_caller_still_falls_back_to_a_claude_default(
    monkeypatch: pytest.MonkeyPatch, codex_profile: str
) -> None:
    """The Codex profile in the table must not capture a Claude caller."""
    _deny(monkeypatch)

    result = runner.run_hook("guard", profile="ghost", stdin_text=json.dumps(CLAUDE_PRE_TOOL_USE))

    assert result.exit_code == 2
    assert "blocked" in result.stderr
    assert "'lazy'" in result.stderr


def test_a_codex_caller_with_no_codex_profile_refuses(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None
) -> None:
    """Every declared profile is Claude Code's: nothing left speaks Codex."""
    register(monkeypatch, "guard", lambda event: HookDecision(), blocking=True)

    result = runner.run_hook("guard", profile="ghost", stdin_text=json.dumps(CODEX_PRE_TOOL_USE))

    assert result.exit_code == 2
    assert "ghost" in result.stderr
    assert "codex" in result.stderr


@pytest.fixture
def two_codex_profiles(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "lazy"\n\n'
        f'[profiles.lazy]\nconfig_dir = "{tmp_path / "lazy"}"\nroots = ["~"]\n\n'
        f'[profiles.cx1]\nconfig_dir = "{tmp_path / "cx1"}"\nroots = ["~"]\nagent = "codex"\n\n'
        f'[profiles.cx2]\nconfig_dir = "{tmp_path / "cx2"}"\nroots = ["~"]\nagent = "codex"\n'
    )
    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: cfg)


def test_a_codex_caller_with_two_codex_profiles_refuses(
    monkeypatch: pytest.MonkeyPatch, two_codex_profiles: None
) -> None:
    """Picking one of two would pick a memory scope; the brief allows exactly one."""
    register(monkeypatch, "guard", lambda event: HookDecision(), blocking=True)

    result = runner.run_hook("guard", profile="ghost", stdin_text=json.dumps(CODEX_PRE_TOOL_USE))

    assert result.exit_code == 2
    assert "cx1" in result.stderr
    assert "cx2" in result.stderr


@pytest.fixture
def codex_default(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "codex"\n\n'
        '[profiles]\ndefault = "cx1"\n\n'
        f'[profiles.cx1]\nconfig_dir = "{tmp_path / "cx1"}"\nroots = ["~"]\n\n'
        f'[profiles.cx2]\nconfig_dir = "{tmp_path / "cx2"}"\nroots = ["~"]\n'
    )
    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: cfg)


def test_a_codex_caller_prefers_a_codex_default_over_counting(
    monkeypatch: pytest.MonkeyPatch, codex_default: None
) -> None:
    _deny(monkeypatch)

    result = runner.run_hook("guard", profile="ghost", stdin_text=json.dumps(CODEX_PRE_TOOL_USE))

    assert result.exit_code == 0
    assert json.loads(result.stdout or "{}")["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "'cx1'" in result.stderr


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(PRE_TOOL_USE, id="neither-marker"),
        pytest.param({**CODEX_PRE_TOOL_USE, "prompt_id": "p1"}, id="both-markers"),
        pytest.param({**CODEX_PRE_TOOL_USE, "turn_id": None}, id="turn-id-null"),
        pytest.param({**CLAUDE_PRE_TOOL_USE, "prompt_id": 7}, id="prompt-id-int"),
    ],
)
def test_an_unidentifiable_caller_on_an_unknown_profile_refuses(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None, payload: dict
) -> None:
    """No guessing: a caller the payload does not name keeps the old refusal,
    even for a benign command and even with a resolvable default."""
    register(monkeypatch, "guard", lambda event: HookDecision(), blocking=True)

    result = runner.run_hook("guard", profile="ghost", stdin_text=json.dumps(payload))

    assert result.exit_code == 2
    assert "ghost" in result.stderr
