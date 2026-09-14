"""Both entry points reach a builtin through the runner, and agree on the bytes.

`lh hook <name>` is what the agent's settings file invokes; `lh hooks run
<event>` is what a developer debugs with. They were two execution mechanisms —
an in-process `main()` call and a subprocess over the module file — so a change
to one was invisible to the other, and
`specs/designs/2026-09-13-multi-agent-harness-design.md` (decision 1) moves both
in the same step for exactly that reason. The agreement test here is what keeps
them one mechanism afterwards.
"""

from __future__ import annotations

import json
import shlex
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.agents.base import HookDecision, HookEvent, Verdict
from lazy_harness.cli.main import cli
from lazy_harness.deploy.engine import hook_command
from lazy_harness.hooks.engine import run_hooks_for_event
from lazy_harness.hooks.loader import _BUILTIN_HOOKS, BuiltinHookSpec, HookInfo

PRE_TOOL_USE = {
    "hook_event_name": "PreToolUse",
    "session_id": "s1",
    "cwd": "/tmp",
    "transcript_path": "/tmp/t.jsonl",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf /"},
}


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No profile table, so a made-up profile name is not rejected as a typo."""
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))


def register(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    main: object,
    *,
    migrated: bool,
    blocking: bool = False,
) -> None:
    """Register a builtin backed by a module built for this test."""
    module_name = f"lazy_harness_test_entry_point_{name.replace('-', '_')}"
    module = types.ModuleType(module_name)
    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setitem(
        _BUILTIN_HOOKS,
        name,
        BuiltinHookSpec(module=module_name, blocking=blocking, migrated=migrated),
    )


def test_hook_invoke_passes_an_explicit_profile_to_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def main(event: HookEvent) -> HookDecision:
        seen.append(event.profile)
        return HookDecision()

    register(monkeypatch, "spy", main, migrated=True)

    result = CliRunner().invoke(
        cli, ["hook", "spy", "--profile", "flex"], input=json.dumps(PRE_TOOL_USE)
    )

    assert result.exit_code == 0, result.output
    assert seen == ["flex"]


@pytest.mark.parametrize("profile", ["work laptop", "it's-mine", "cost$profile"])
def test_the_deployed_command_invokes_cleanly_for_an_awkward_profile(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    """What `deploy` writes has to parse back into the arguments click expects.

    The generator and this entry point are the two halves of one contract, and
    only a test that runs the generated string through the parser covers the
    seam: `--profile work laptop` is a usage error, and click's exit code for a
    usage error is 2 — which on PreToolUse is Claude Code's "block this tool
    call".
    """
    seen: list[str] = []

    def main(event: HookEvent) -> HookDecision:
        seen.append(event.profile)
        return HookDecision()

    register(monkeypatch, "spy", main, migrated=True)
    hook = HookInfo(name="spy", path=Path("/nonexistent/spy.py"), is_builtin=True)

    argv = shlex.split(hook_command(hook, profile=profile))

    result = CliRunner().invoke(cli, argv[1:], input=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0, result.output
    assert seen == [profile]


def test_hook_invoke_falls_back_to_todays_profile_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deployed commands predate the flag, so its absence cannot be a failure.

    The agent's settings file says `lh hook <name>` today and `deploy` does not
    rewrite it in this step: making `--profile` required would break every
    installed hook between one step and the next.
    """
    import lazy_harness.hooks.builtins._shared as shared

    monkeypatch.setattr(shared, "profile_name", lambda: "from-environment")
    seen: list[str] = []

    def main(event: HookEvent) -> HookDecision:
        seen.append(event.profile)
        return HookDecision()

    register(monkeypatch, "spy", main, migrated=True)

    result = CliRunner().invoke(cli, ["hook", "spy"], input=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0, result.output
    assert seen == ["from-environment"]


def test_an_unmigrated_builtin_is_still_called_with_no_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The marker routes, and until a module migrates it routes to the old path."""
    calls: list[str] = []

    register(monkeypatch, "legacy", lambda: calls.append("no-args"), migrated=False)

    result = CliRunner().invoke(cli, ["hook", "legacy"], input=json.dumps(PRE_TOOL_USE))

    assert result.exit_code == 0, result.output
    assert calls == ["no-args"]


def test_the_engine_runs_a_migrated_builtin_without_spawning_a_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The path on the `HookInfo` does not exist, so a subprocess would fail."""
    register(
        monkeypatch,
        "spy",
        lambda event: HookDecision(system_message="ran"),
        migrated=True,
    )
    hook = HookInfo(name="spy", path=Path("/nonexistent/spy.py"), is_builtin=True)

    results = run_hooks_for_event(
        [hook], event="pre_tool_use", payload=PRE_TOOL_USE, profile="lazy"
    )

    assert [r.exit_code for r in results] == [0]
    assert json.loads(results[0].stdout) == {"systemMessage": "ran"}


def test_the_engine_still_executes_an_unmigrated_builtin_as_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Nothing is migrated yet, so `lh hooks run` must keep running the module."""
    script = tmp_path / "legacy_hook.py"
    script.write_text("print('from the file')\n")
    register(monkeypatch, "legacy", lambda: None, migrated=False)
    hook = HookInfo(name="legacy", path=script, is_builtin=True)

    results = run_hooks_for_event([hook], event="pre_tool_use", payload=PRE_TOOL_USE)

    assert results[0].stdout.strip() == "from the file"


def test_the_engine_still_executes_a_user_hook_as_a_file(tmp_path: Path) -> None:
    """A hook the registry never heard of has no `main(event)` to call."""
    script = tmp_path / "mine.py"
    script.write_text("print('user hook')\n")
    hook = HookInfo(name="mine", path=script, is_builtin=False)

    results = run_hooks_for_event([hook], event="pre_tool_use", payload=PRE_TOOL_USE)

    assert results[0].stdout.strip() == "user hook"


def test_both_entry_points_produce_the_same_three_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate: two paths answering one question are asserted to agree.

    All three channels carry something — a refusal on stderr, JSON on stdout
    and a non-zero exit — so an entry point that drops one of them fails here
    instead of passing by writing nothing.
    """
    decision = HookDecision(verdict=Verdict.DENY, reason="nope", system_message="heads up")
    register(monkeypatch, "guard", lambda event: decision, migrated=True, blocking=True)
    payload = json.dumps(PRE_TOOL_USE)

    invoked = CliRunner().invoke(cli, ["hook", "guard", "--profile", "lazy"], input=payload)
    engine = run_hooks_for_event(
        [HookInfo(name="guard", path=Path("/nonexistent/guard.py"), is_builtin=True)],
        event="pre_tool_use",
        payload=PRE_TOOL_USE,
        profile="lazy",
    )[0]

    assert (invoked.stdout, invoked.stderr, invoked.exit_code) == (
        engine.stdout,
        engine.stderr,
        engine.exit_code,
    )
    assert invoked.exit_code == 2
    assert invoked.stderr == "nope"
    assert json.loads(invoked.stdout) == {"systemMessage": "heads up"}
