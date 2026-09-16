"""Integration smoke tests — spawn the hook modules as Claude Code would."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_command(
    hook: str, payload: dict | str, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Spawn `lh hook <name>` — what a migrated builtin's settings.json says.

    `python -m <module>` stops reaching a migrated hook: its `main()` takes an
    event, so the module has no `__main__` path left. This is the command the
    agent actually runs, which is the only thing an integration smoke test of
    a deployed hook is worth asserting about.
    """
    import os

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, "-c", "from lazy_harness.cli.main import cli; cli()", "hook", hook],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_pre_tool_use_security_blocks_rm_rf(tmp_path: Path) -> None:
    result = _run_command(
        "pre-tool-use-security",
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/foo"}},
        env_extra={"LH_CONFIG_DIR": str(tmp_path)},
    )
    assert result.returncode == 2
    assert "Blocked by lazy-harness PreToolUse" in result.stderr
    assert "filesystem" in result.stderr


def test_pre_tool_use_security_allows_innocent_command(tmp_path: Path) -> None:
    result = _run_command(
        "pre-tool-use-security",
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        env_extra={"LH_CONFIG_DIR": str(tmp_path)},
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_post_tool_use_format_reformats_the_edited_python_file(tmp_path: Path) -> None:
    """Exit 0 alone proves nothing here, and after the migration it proves less.

    A migrated module has no `__main__` path left, so `python -m <module>`
    imports it, defines `main(event)` and exits 0 without running anything —
    the same exit code the working hook returns. The file on disk is what
    tells the two apart, and `lh hook <name>` is the command settings.json
    actually carries.
    """
    py = tmp_path / "foo.py"
    py.write_text("x  =  1\n")

    result = _run_command(
        "post-tool-use-format",
        {"tool_name": "Edit", "tool_input": {"file_path": str(py)}},
    )

    assert result.returncode == 0, result.stderr
    assert py.read_text() == "x = 1\n"


def test_empty_stdin_is_refused_or_waved_through_by_the_failure_policy() -> None:
    """Decision 3, through the command the agent runs rather than around it.

    This used to assert exit 0 for both, and passed for a reason that had
    stopped being true: `python -m <module>` never reaches the runner, so
    neither hook's failure policy was exercised. Through `lh hook` they differ,
    and the difference is the policy — `blocking` in the registry decides it.
    Exit 0 with no output is how a hook says "no objection", so a guard that
    degraded there would turn its own crash into an approval.
    """
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS

    for hook in ("pre-tool-use-security", "post-tool-use-format"):
        expected = 2 if _BUILTIN_HOOKS[hook].blocking else 0
        result = _run_command(hook, "")
        assert result.returncode == expected, f"{hook}: {result.stderr}"
        assert "unparseable payload" in result.stderr
        assert result.stdout == ""
