"""Unit tests for post_tool_use_format hook.

The hook takes a `HookEvent` and returns a `HookDecision`; the runner owns
stdin, both channels and the exit code. What is left here is the hook's own
two gates — which tool, and which suffix — and its fail-soft branch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lazy_harness.agents.base import (
    FileEdit,
    HookDecision,
    HookEvent,
    Operation,
    ToolCall,
)

#: The profile every event below is invoked under, and the only directory the
#: hook is entitled to write into.
PROFILE = "gate"


def _event(
    *,
    tool_name: str = "Edit",
    operation: Operation | None = Operation.MODIFY_FILE,
    paths: tuple[str, ...] = ("/abs/foo.py",),
    tool: ToolCall | None | object = ...,
) -> HookEvent:
    call = (
        ToolCall(
            native_name=tool_name,
            operation=operation,
            edits=tuple(FileEdit(path=Path(p)) for p in paths),
        )
        if tool is ...
        else tool
    )
    return HookEvent(
        event="post_tool_use",
        profile=PROFILE,
        session_id="s1",
        cwd=Path("/work"),
        transcript_path=None,
        tool=call,  # type: ignore[arg-type]
    )


def _ran(fake_run: MagicMock) -> list[list[str]]:
    return [call.args[0] for call in fake_run.call_args_list]


def test_runs_ruff_format_on_a_python_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock(return_value=subprocess.CompletedProcess([], returncode=0))
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event()) == HookDecision()

    fake_run.assert_called_once()
    args, kwargs = fake_run.call_args
    assert args[0] == ["ruff", "format", "/abs/foo.py"]
    assert kwargs.get("check") is False
    assert kwargs.get("timeout") == 10


def test_runs_ruff_format_on_a_python_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock(return_value=subprocess.CompletedProcess([], returncode=0))
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event(tool_name="Write", paths=("/abs/bar.py",))) == HookDecision()

    assert _ran(fake_run) == [["ruff", "format", "/abs/bar.py"]]


def test_a_notebook_edit_naming_a_python_path_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The widening `Operation.MODIFY_FILE` would have let in, stated as a test.

    `_TOOL_OPERATIONS` maps `NotebookEdit` to `MODIFY_FILE` alongside `Edit` and
    `Write` (`claude_code.py:97`), and this hook carries no matcher, so it is
    invoked on every PostToolUse. The `.py` suffix re-check does not save it:
    nothing in `ToolCall` makes a notebook's path end in `.ipynb`, so a
    `NotebookEdit` whose normalised path is `notebook.py` would get Ruff run
    over a file that was never Python source.

    Gating on `native_name` as well as on the operation is what keeps that out.
    """
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    event = _event(tool_name="NotebookEdit", paths=("/abs/notebook.py",))

    assert mod.main(event) == HookDecision()
    assert event.tool is not None
    assert event.tool.operation is Operation.MODIFY_FILE, "the widening has to be reachable"
    fake_run.assert_not_called()


def test_skips_non_python_files(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event(paths=("/abs/readme.md",))) == HookDecision()

    fake_run.assert_not_called()


def test_formats_only_the_python_files_of_a_multi_file_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`edits` is plural because another agent's patch tool touches several files.

    Claude Code never sends more than one, so this is the branch a translated
    payload reaches first — and the suffix gate has to apply per file, not to
    whichever one happens to come out of the tuple first.
    """
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock(return_value=subprocess.CompletedProcess([], returncode=0))
    monkeypatch.setattr("subprocess.run", fake_run)

    event = _event(paths=("/abs/a.py", "/abs/notes.md", "/abs/b.py"))

    assert mod.main(event) == HookDecision()
    assert _ran(fake_run) == [["ruff", "format", "/abs/a.py"], ["ruff", "format", "/abs/b.py"]]


def test_skips_a_tool_that_modifies_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    event = _event(tool_name="Read", operation=Operation.READ_FILE, paths=())

    assert mod.main(event) == HookDecision()
    fake_run.assert_not_called()


def test_abstains_when_the_event_carries_no_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event(tool=None)) == HookDecision()
    fake_run.assert_not_called()


def test_abstains_when_the_tool_call_names_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)

    assert mod.main(_event(paths=())) == HookDecision()
    fake_run.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("ruff not found"), PermissionError(), subprocess.TimeoutExpired("ruff", 10)],
    ids=["missing", "not-executable", "timeout"],
)
def test_abstains_when_ruff_cannot_run(
    error: Exception, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A formatter failure must never fail the agent's turn."""
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "agent"))
    monkeypatch.setattr("subprocess.run", MagicMock(side_effect=error))

    assert mod.main(_event()) == HookDecision()


def test_logs_into_the_invoked_profile_when_ruff_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Swallowing the error silently made a formatter that never runs look
    identical to one that runs on every edit — and the line has to land in the
    profile the hook was invoked with, not in whatever the global agent names.
    """
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    lh_config = tmp_path / "lhconfig"
    lh_config.mkdir()
    gate = tmp_path / "gate-home"
    (lh_config / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        '[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "other"\n\n'
        f'[profiles.{PROFILE}]\nconfig_dir = "{gate}"\n\n'
        f'[profiles.other]\nconfig_dir = "{tmp_path / "other-home"}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setattr("subprocess.run", MagicMock(side_effect=FileNotFoundError("ruff")))

    assert mod.main(_event()) == HookDecision()

    log = (gate / "logs" / "hooks.log").read_text()
    assert "post-tool-use-format: ruff unavailable (FileNotFoundError)" in log
    assert "left /abs/foo.py unformatted" in log


def test_a_broken_log_path_does_not_reach_the_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The fail-soft branch has its own fail-soft branch, and it is load-bearing.

    `_log_unavailable` loads config and resolves an agent, either of which can
    raise on a machine mid-`lh init`. This hook runs on every tool call, so a
    raise here would surface on every edit.
    """
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    monkeypatch.setattr("subprocess.run", MagicMock(side_effect=FileNotFoundError("ruff")))
    monkeypatch.setattr(
        "lazy_harness.hooks.builtins._shared.agent_dir_for",
        MagicMock(side_effect=RuntimeError("no agent")),
    )

    assert mod.main(_event()) == HookDecision()


def test_the_registry_declares_what_this_hook_reasons_about() -> None:
    """Declared, not inferred from a matcher — this hook carries none at all."""
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS

    spec = _BUILTIN_HOOKS["post-tool-use-format"]

    assert spec.event == "post_tool_use"
    assert spec.operations == frozenset({Operation.MODIFY_FILE})
    assert spec.blocking is False
    assert spec.signals == frozenset()


def test_the_deployed_matcher_still_reaches_every_inspected_tool() -> None:
    """`INSPECTED_TOOLS` survives the migration, and so does the gate over it.

    `tests/unit/test_hook_matcher_coverage.py` picks its subjects by grepping
    each builtin's source for the string `tool_name`, which a migration removes
    by definition — `pre-tool-use-security` had already fallen out of that
    coverage unnoticed. PR #320 re-keys the detection on declared operations;
    until it lands, this is the assertion that keeps this hook covered.
    """
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.hooks.builtins.post_tool_use_format import INSPECTED_TOOLS
    from lazy_harness.hooks.loader import resolve_hook

    hook = resolve_hook("post-tool-use-format", event="post_tool_use")
    assert hook is not None
    assert hook.matcher is None, "no per-hook matcher: the event default has to cover the set"

    generated = ClaudeCodeAdapter()._generate_hook_config({"post_tool_use": ["cmd"]})
    matcher = generated["PostToolUse"][0]["matcher"]

    uncovered = sorted(t for t in INSPECTED_TOOLS if matcher not in ("", "*") and t not in matcher)
    assert uncovered == [], f"matcher {matcher!r} never reaches {uncovered}"
