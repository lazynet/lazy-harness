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

from lazy_harness.cli.hooks_cmd import hook_invoke
from lazy_harness.hooks.loader import BuiltinHookSpec


def _register_fake_hook(monkeypatch: pytest.MonkeyPatch, name: str, main: object) -> None:
    """Register a builtin hook whose `main()` is under the test's control."""
    module_name = f"lazy_harness_test_hooks.{name.replace('-', '_')}"
    module = ModuleType(module_name)
    module.main = main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setitem(
        __import__("lazy_harness.cli.hooks_cmd", fromlist=["_BUILTIN_HOOKS"])._BUILTIN_HOOKS,
        name,
        BuiltinHookSpec(module=module_name),
    )


def test_launcher_propagates_a_blocking_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def main() -> None:
        sys.stderr.write("blocked\n")
        sys.exit(2)

    _register_fake_hook(monkeypatch, "fake-blocking", main)

    result = CliRunner().invoke(hook_invoke, ["fake-blocking"])

    assert result.exit_code == 2


def test_launcher_still_exits_zero_when_a_hook_permits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def main() -> None:
        sys.exit(0)

    _register_fake_hook(monkeypatch, "fake-permitting", main)

    result = CliRunner().invoke(hook_invoke, ["fake-permitting"])

    assert result.exit_code == 0


def test_launcher_degrades_to_zero_when_a_hook_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crashing hook must not take the session down with it."""

    def main() -> None:
        raise RuntimeError("boom")

    _register_fake_hook(monkeypatch, "fake-crashing", main)

    result = CliRunner().invoke(hook_invoke, ["fake-crashing"])

    assert result.exit_code == 0
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
