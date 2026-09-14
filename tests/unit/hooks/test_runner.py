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


def register(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    main: object,
    *,
    blocking: bool,
) -> None:
    """Register a builtin backed by a module built for this test."""
    module_name = f"lazy_harness_test_builtin_{name.replace('-', '_')}"
    module = types.ModuleType(module_name)
    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setitem(
        _BUILTIN_HOOKS,
        name,
        BuiltinHookSpec(module=module_name, blocking=blocking),
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


@pytest.mark.parametrize(
    ("stdin_text", "reason"),
    [("not json at all", "payload"), ("[]", "payload"), ("null", "payload")],
)
def test_unparseable_payload_refuses_for_a_blocking_hook(
    monkeypatch: pytest.MonkeyPatch, stdin_text: str, reason: str
) -> None:
    register(monkeypatch, "guard", lambda event: HookDecision(), blocking=True)

    result = runner.run_hook("guard", profile="lazy", stdin_text=stdin_text)

    assert result.exit_code == 2
    assert reason in result.stderr


@pytest.mark.parametrize("stdin_text", ["not json at all", "[]", "null"])
def test_unparseable_payload_lets_an_informational_hook_through(
    monkeypatch: pytest.MonkeyPatch, stdin_text: str
) -> None:
    register(monkeypatch, "notes", lambda event: HookDecision(), blocking=False)

    result = runner.run_hook("notes", profile="lazy", stdin_text=stdin_text)

    assert result.exit_code == 0
    assert result.stderr != ""


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


def test_unknown_profile_refuses_for_a_blocking_hook(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None
) -> None:
    register(monkeypatch, "guard", lambda event: HookDecision(), blocking=True)

    result = runner.run_hook("guard", profile="ghost", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 2
    assert "ghost" in result.stderr


def test_unknown_profile_lets_an_informational_hook_through(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None
) -> None:
    register(monkeypatch, "notes", lambda event: HookDecision(), blocking=False)

    result = runner.run_hook("notes", profile="ghost", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0
    assert "ghost" in result.stderr


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


def test_a_named_profile_that_is_not_declared_still_refuses(
    monkeypatch: pytest.MonkeyPatch, configured_profiles: None
) -> None:
    """The fallback must not swallow the typo it was added to name.

    An empty profile is "nothing resolved"; a non-empty one that no profile
    declares is a wrong `--profile` in a deployed command, and a hook running
    under the wrong scope writes memory and metrics to the wrong place.
    """
    register(monkeypatch, "guard", lambda event: HookDecision(), blocking=True)

    result = runner.run_hook("guard", profile="lazyy", stdin_text=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 2
    assert "lazyy" in result.stderr
