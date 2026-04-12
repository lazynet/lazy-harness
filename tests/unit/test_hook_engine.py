"""Tests for hook execution engine."""

from __future__ import annotations

from pathlib import Path


def test_execute_hook_python_script(tmp_path: Path) -> None:
    from lazy_harness.hooks.engine import execute_hook
    from lazy_harness.hooks.loader import HookInfo

    script = tmp_path / "test_hook.py"
    script.write_text('import json, sys; print(json.dumps({"status": "ok"}))\n')

    hook = HookInfo(name="test", path=script, is_builtin=False)
    result = execute_hook(hook, event="session_start", payload={}, timeout=5)
    assert result.exit_code == 0
    assert result.hook_name == "test"


def test_execute_hook_with_payload(tmp_path: Path) -> None:
    from lazy_harness.hooks.engine import execute_hook
    from lazy_harness.hooks.loader import HookInfo

    script = tmp_path / "echo_hook.py"
    script.write_text("import sys, json; data = json.load(sys.stdin); print(data.get('cwd', ''))\n")

    hook = HookInfo(name="echo", path=script, is_builtin=False)
    result = execute_hook(hook, event="session_start", payload={"cwd": "/tmp/test"}, timeout=5)
    assert result.exit_code == 0
    assert "/tmp/test" in result.stdout


def test_execute_hook_timeout(tmp_path: Path) -> None:
    from lazy_harness.hooks.engine import execute_hook
    from lazy_harness.hooks.loader import HookInfo

    script = tmp_path / "slow_hook.py"
    script.write_text("import time; time.sleep(10)\n")

    hook = HookInfo(name="slow", path=script, is_builtin=False)
    result = execute_hook(hook, event="session_start", payload={}, timeout=1)
    assert result.exit_code != 0
    assert result.timed_out is True


def test_execute_hook_failure(tmp_path: Path) -> None:
    from lazy_harness.hooks.engine import execute_hook
    from lazy_harness.hooks.loader import HookInfo

    script = tmp_path / "fail_hook.py"
    script.write_text("import sys; sys.exit(1)\n")

    hook = HookInfo(name="fail", path=script, is_builtin=False)
    result = execute_hook(hook, event="session_start", payload={}, timeout=5)
    assert result.exit_code == 1


def test_run_hooks_for_event(tmp_path: Path) -> None:
    from lazy_harness.hooks.engine import run_hooks_for_event
    from lazy_harness.hooks.loader import HookInfo

    script = tmp_path / "ok_hook.py"
    script.write_text("print('ok')\n")

    hooks = [HookInfo(name="ok", path=script, is_builtin=False)]
    results = run_hooks_for_event(hooks, event="session_start", payload={})
    assert len(results) == 1
    assert results[0].exit_code == 0
