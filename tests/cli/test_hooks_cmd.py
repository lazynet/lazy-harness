"""`lh hook` is the transport for a hook's verdict, not just its runner.

Claude Code reads the exit code: 0 permits, 2 blocks. A launcher that
normalises every outcome to 0 turns `pre-tool-use-security` into a hook that
prints a refusal and lets the command through anyway.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from click.testing import CliRunner

from lazy_harness.agents.base import HookDecision, HookEvent, Verdict
from lazy_harness.cli.hooks_cmd import hook_invoke
from lazy_harness.hooks import loader
from lazy_harness.hooks.loader import BuiltinHookSpec

#: A PreToolUse payload the runner can parse. `lh hook` reads stdin through the
#: profile's adapter now, so an invocation with no input fails as an unparseable
#: payload before it ever reaches `main()` — which is a real behaviour, but not
#: the one any test below is about.
_PRE_TOOL_USE = json.dumps(
    {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "cwd": "/tmp",
        "transcript_path": "/tmp/t.jsonl",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
    }
)


def _register_fake_hook(
    monkeypatch: pytest.MonkeyPatch, name: str, main: object, *, blocking: bool = False
) -> None:
    """Register a builtin hook whose `main(event)` is under the test's control."""
    module_name = f"lazy_harness_test_hooks.{name.replace('-', '_')}"
    module = ModuleType(module_name)
    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setitem(
        loader._BUILTIN_HOOKS,
        name,
        BuiltinHookSpec(module=module_name, event="pre_tool_use", blocking=blocking),
    )


def test_launcher_propagates_a_blocking_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def main(event: HookEvent) -> HookDecision:
        return HookDecision(verdict=Verdict.DENY, reason="blocked")

    _register_fake_hook(monkeypatch, "fake-blocking", main, blocking=True)

    result = CliRunner().invoke(hook_invoke, ["fake-blocking"], input=_PRE_TOOL_USE)

    assert result.exit_code == 2
    assert "blocked" in result.output


def test_launcher_still_exits_zero_when_a_hook_permits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def main(event: HookEvent) -> HookDecision:
        return HookDecision()

    _register_fake_hook(monkeypatch, "fake-permitting", main)

    result = CliRunner().invoke(hook_invoke, ["fake-permitting"], input=_PRE_TOOL_USE)

    assert result.exit_code == 0


def test_launcher_degrades_to_zero_when_a_hook_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crashing hook must not take the session down with it.

    Non-blocking on purpose: `run_hook` answers a raising *blocking* hook with
    exit 2, so registering this one as blocking would assert the opposite
    policy while looking like the same test.
    """

    def main(event: HookEvent) -> HookDecision:
        raise RuntimeError("boom")

    _register_fake_hook(monkeypatch, "fake-crashing", main)

    result = CliRunner().invoke(hook_invoke, ["fake-crashing"], input=_PRE_TOOL_USE)

    assert result.exit_code == 0
    assert "RuntimeError" in result.output


def test_a_blocking_hook_that_raises_still_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the degradation policy, and the asymmetric one.

    A guard that crashes has not decided the command is safe. `run_hook` turns
    its exception into exit 2 rather than into silence, so the test above's
    exit 0 is a statement about non-blocking hooks and not about crashes.
    """

    def main(event: HookEvent) -> HookDecision:
        raise RuntimeError("boom")

    _register_fake_hook(monkeypatch, "fake-blocking-crasher", main, blocking=True)

    result = CliRunner().invoke(hook_invoke, ["fake-blocking-crasher"], input=_PRE_TOOL_USE)

    assert result.exit_code == 2
    assert "RuntimeError" in result.output


def test_launcher_exits_zero_for_an_unknown_hook() -> None:
    result = CliRunner().invoke(hook_invoke, ["no-such-hook"])

    assert result.exit_code == 0
    assert "Unknown hook" in result.output


def test_security_hook_blocks_through_the_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end the deployment actually uses: settings.json runs `lh hook`."""
    (tmp_path / "config.toml").write_text('[harness]\nversion = "1"\n')
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "agent"))
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        }
    )

    result = CliRunner().invoke(hook_invoke, ["pre-tool-use-security"], input=payload)

    assert result.exit_code == 2
