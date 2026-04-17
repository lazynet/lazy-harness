"""Integration smoke tests — spawn the hook modules as Claude Code would."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_hook(
    module: str, payload: dict | str, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    import os

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, "-m", module],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_pre_tool_use_security_blocks_rm_rf(tmp_path: Path) -> None:
    result = _run_hook(
        "lazy_harness.hooks.builtins.pre_tool_use_security",
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/foo"}},
        env_extra={"LH_CONFIG_DIR": str(tmp_path)},
    )
    assert result.returncode == 2
    assert "Blocked by lazy-harness PreToolUse" in result.stderr
    assert "filesystem" in result.stderr


def test_pre_tool_use_security_allows_innocent_command(tmp_path: Path) -> None:
    result = _run_hook(
        "lazy_harness.hooks.builtins.pre_tool_use_security",
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        env_extra={"LH_CONFIG_DIR": str(tmp_path)},
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_post_tool_use_format_exits_zero_on_python_edit(tmp_path: Path) -> None:
    py = tmp_path / "foo.py"
    py.write_text("x=1\n")
    result = _run_hook(
        "lazy_harness.hooks.builtins.post_tool_use_format",
        {"tool_name": "Edit", "tool_input": {"file_path": str(py)}},
    )
    assert result.returncode == 0


def test_both_hooks_exit_zero_on_empty_stdin() -> None:
    for module in (
        "lazy_harness.hooks.builtins.pre_tool_use_security",
        "lazy_harness.hooks.builtins.post_tool_use_format",
    ):
        result = _run_hook(module, "")
        assert result.returncode == 0, f"{module} non-zero on empty stdin"
