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
import os
import shlex
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.agents.base import HookDecision, HookEvent
from lazy_harness.cli.main import cli
from lazy_harness.deploy.engine import hook_command
from lazy_harness.hooks.engine import execute_hook, run_hooks_for_event
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


def test_the_engine_reaches_a_migrated_builtin_through_the_deployed_command() -> None:
    """The path on the `HookInfo` does not exist, so the file route cannot answer.

    This replaces an assertion that the engine ran a migrated builtin *in this
    process*. Nothing can impose a timeout on a synchronous in-process call, so
    that branch became the deployed command in a subprocess; what the missing
    path proves is now the route taken, not the absence of a process.

    A real registry name rather than one registered for the test: the child
    resolves `_BUILTIN_HOOKS` for itself, and a name monkeypatched into this
    process does not exist on the other side of the boundary.
    """
    hook = HookInfo(
        name="pre-tool-use-security",
        path=Path("/nonexistent/guard.py"),
        is_builtin=True,
    )

    results = run_hooks_for_event(
        [hook], event="pre_tool_use", payload=PRE_TOOL_USE, profile="lazy"
    )

    assert [r.exit_code for r in results] == [2]
    assert "Blocked by lazy-harness" in results[0].stderr


def test_a_migrated_builtin_is_held_to_its_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`timed_out` has to be measured, not declared.

    The in-process call this branch used to make ignored `timeout` entirely and
    returned `timed_out=False` unconditionally — a field that lies by
    construction. A synchronous in-process call cannot be interrupted in
    Python, so a thread would report the timeout without imposing it: only a
    process boundary can actually stop the work.

    The child is made slow without putting a sleep in production code.
    `sitecustomize` is imported at interpreter startup, ahead of whatever `-c`
    runs, so a copy of it on PYTHONPATH delays the real entry point itself.
    """
    slow = tmp_path / "slow-site"
    slow.mkdir()
    (slow / "sitecustomize.py").write_text("import time\n\ntime.sleep(30)\n")
    inherited = os.environ.get("PYTHONPATH")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(p for p in (str(slow), inherited) if p))
    register(monkeypatch, "spy", lambda event: HookDecision(), migrated=True)
    hook = HookInfo(name="spy", path=Path("/nonexistent/spy.py"), is_builtin=True)

    result = execute_hook(
        hook, event="pre_tool_use", payload=PRE_TOOL_USE, timeout=1, profile="lazy"
    )

    assert result.timed_out is True
    assert result.exit_code == -1
    assert "timed out after 1s" in result.stderr


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


#: A `/goal` declaration as Claude Code writes it into the transcript.
_GOAL_ATTACHMENT = json.dumps({"type": "attachment", "attachment": {"type": "goal_status"}})

_STOP_CONFIG = '[harness]\nversion = "1"\n\n[loops]\ninject_goal_prompt = true\n'


def _refused_payload(hook_name: str, tmp_path: Path) -> dict:
    """A payload the named guard actually refuses.

    The pair is chosen so that between them all three channels carry something:
    `pre-tool-use-security` refuses on stderr with exit 2, and
    `stop-verify-guard` refuses on *stdout* with exit 0 in Spanish — so the
    exit code, both streams and a non-ASCII encoding are each covered by a case
    that would notice if the wrapper dropped it.
    """
    if hook_name == "pre-tool-use-security":
        return dict(PRE_TOOL_USE)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(_GOAL_ATTACHMENT + "\n", encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "config.toml").write_text(_STOP_CONFIG, encoding="utf-8")
    return {
        "hook_event_name": "Stop",
        "session_id": "0193b0de-1111-2222-3333-444455556666",
        "transcript_path": str(transcript),
    }


@pytest.mark.parametrize("hook_name", ["pre-tool-use-security", "stop-verify-guard"])
def test_both_entry_points_produce_the_same_three_channels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hook_name: str
) -> None:
    """The gate: two paths answering one question are asserted to agree.

    `lh hooks run` now spawns `lh hook` rather than deciding for itself, so the
    agreement is no longer between two decision mechanisms. It is between the
    entry point and the subprocess wrapper over it, which is exactly where
    bytes can still be lost: the stream encoding, a trailing newline, and an
    exit code that has to survive `sys.exit` in a child instead of a return.

    Each side gets its own `LH_DATA_DIR`. `stop-verify-guard` blocks once per
    session and records that it did, so two invocations sharing one metrics
    store would disagree by design rather than because of the wrapper.
    """
    payload = _refused_payload(hook_name, tmp_path)
    event = "pre_tool_use" if hook_name == "pre-tool-use-security" else "session_stop"

    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data-engine"))
    engine = run_hooks_for_event(
        [HookInfo(name=hook_name, path=Path("/nonexistent/hook.py"), is_builtin=True)],
        event=event,
        payload=payload,
        profile="lazy",
    )[0]

    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data-cli"))
    invoked = CliRunner().invoke(
        cli, ["hook", hook_name, "--profile", "lazy"], input=json.dumps(payload)
    )

    assert (invoked.stdout, invoked.stderr, invoked.exit_code) == (
        engine.stdout,
        engine.stderr,
        engine.exit_code,
    )
    if hook_name == "pre-tool-use-security":
        assert (invoked.exit_code, invoked.stdout) == (2, "")
        assert "Blocked by lazy-harness" in invoked.stderr
    else:
        assert (invoked.exit_code, invoked.stderr) == (0, "")
        assert "verificación" in json.loads(invoked.stdout)["reason"]
