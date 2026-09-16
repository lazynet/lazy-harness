"""Tests for the Read-size PreToolUse hook."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.agents.base import HookEvent, Operation, ToolCall


def _event(
    *,
    path: Path | None,
    offset: int | None = None,
    limit: int | None = None,
    native_name: str = "Read",
    operation: Operation | None = Operation.READ_FILE,
    tool: bool = True,
) -> HookEvent:
    """A `pre_tool_use` event carrying one normalised tool call.

    Built by hand rather than through the adapter so that `native_name` and
    `operation` can disagree: that pairing is what the narrowing below is about,
    and no Claude Code payload produces it today.
    """
    return HookEvent(
        event="pre_tool_use",
        profile="p",
        session_id="s",
        cwd=Path("/nonexistent"),
        transcript_path=None,
        tool=ToolCall(
            native_name=native_name,
            operation=operation,
            reads=(path,) if path is not None else (),
            offset=offset,
            limit=limit,
        )
        if tool
        else None,
    )


def test_warns_on_a_whole_file_read_of_a_large_file(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    big = tmp_path / "main.yaml"
    big.write_text("key: value\n" * 3000)

    decision = main(_event(path=big))

    assert "3000 lines" in decision.system_message
    assert str(big) in decision.system_message


def test_the_warning_carries_no_verdict(tmp_path: Path) -> None:
    """`pre_tool_use` honours `DENY`, so abstention has to be explicit here.

    This hook is informational: it warns and lets the read through. A decision
    that named a verdict would turn a cost notice into a permission decision on
    the one event where Claude Code acts on it — and `HookDecision.verdict`
    defaulting to `None` is the thing that has to keep holding.
    """
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    big = tmp_path / "main.yaml"
    big.write_text("key: value\n" * 3000)

    decision = main(_event(path=big))

    assert decision.system_message, "the warning branch is the one under test"
    assert decision.verdict is None
    assert decision.reason == ""
    assert decision.additional_context == ""


def test_stays_silent_when_the_read_is_already_bounded(tmp_path: Path) -> None:
    """A caller that passed limit/offset already did the right thing."""
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    big = tmp_path / "main.yaml"
    big.write_text("key: value\n" * 3000)

    assert main(_event(path=big, limit=200)).system_message == ""


def test_an_offset_of_zero_is_a_bound(tmp_path: Path) -> None:
    """`0` is a legitimate start offset, and falsy.

    `ToolCall.offset` documents `None` — not 0 — as "unbounded", and the
    adapter's `_as_int` preserves the difference. A guard written as
    `if event.tool.offset:` would warn on a read that named its region, which is
    the opposite of what this hook is for.
    """
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    big = tmp_path / "main.yaml"
    big.write_text("key: value\n" * 3000)

    assert main(_event(path=big, offset=0)).system_message == ""


def test_stays_silent_on_a_small_file(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    small = tmp_path / "notes.md"
    small.write_text("line\n" * 50)

    assert main(_event(path=small)).system_message == ""


def test_stays_silent_for_a_tool_that_does_not_read_a_file(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    big = tmp_path / "main.yaml"
    big.write_text("key: value\n" * 3000)

    decision = main(_event(path=big, native_name="NotebookEdit", operation=Operation.MODIFY_FILE))

    assert decision.system_message == ""


def test_stays_silent_for_a_read_file_tool_this_hook_does_not_inspect(tmp_path: Path) -> None:
    """The narrowing trap 3 is about, in this hook's spelling.

    `_TOOL_OPERATIONS` maps only `Read` to `READ_FILE` today, so gating on the
    operation alone happens to be equivalent — *today*. `INSPECTED_TOOLS` is the
    contract `tests/unit/test_hook_matcher_coverage.py` holds the deployed
    matcher against, and a hook whose guard no longer reads it would keep
    passing that gate while acting on a tool the matcher never named. This is
    the pairing no shipped payload produces: `READ_FILE` under another name.
    """
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    big = tmp_path / "main.yaml"
    big.write_text("key: value\n" * 3000)

    decision = main(_event(path=big, native_name="ReadManyFiles"))

    assert decision.system_message == ""


def test_stays_silent_when_the_file_is_missing(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    assert main(_event(path=tmp_path / "nope.txt")).system_message == ""


def test_stays_silent_when_the_call_names_no_path() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    assert main(_event(path=None)).system_message == ""


def test_stays_silent_on_an_event_carrying_no_tool_call() -> None:
    """The shape an agent whose adapter parses no tool delivers.

    `CodexAdapter._parse_tool` builds no `FileEdit` and no `reads` and returns
    `operation=None`; a payload naming no tool at all yields `event.tool is
    None`. Both have to reach a bare `HookDecision()` rather than an attribute
    error on a hook wired to `pre_tool_use` on every agent.
    """
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    assert main(_event(path=None, tool=False)).system_message == ""


def test_the_bypass_env_var_silences_the_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import main

    big = tmp_path / "main.yaml"
    big.write_text("key: value\n" * 3000)
    monkeypatch.setenv("LH_READ_SIZE_BYPASS", "1")

    assert main(_event(path=big)).system_message == ""
