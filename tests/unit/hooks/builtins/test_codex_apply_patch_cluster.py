"""The five builtins that were inert on Codex's native edit path, end to end.

Every event here is built by the **shipped** `CodexAdapter` from a payload
copied out of `specs/designs/codex-evidence.md` (§1, probe 4c) — not by hand.
A hand-built `ToolCall` would assert that the builtins act on a structure, which
was never in doubt; what was in doubt is whether the adapter produces one from
what Codex actually sends, and only the adapter can answer that.

The gap these close, from the evidence's own reconciliation table (:378-395):
`apply_patch` arrives with `tool_input.command` holding a patch blob, so a hook
gating on `INSPECTED_TOOLS` missed it by name, and a hook gating on `tool.edits`
missed it because nothing parsed the blob. Both had to be fixed, and
`pre-tool-use-memory-size` needed a third fix the evidence does not name — see
`test_memory_size_projects_a_patched_file` below.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lazy_harness.agents.base import HookEvent, Operation
from lazy_harness.agents.codex import CodexAdapter

PROFILE = "gate"


def _blob(*sections: str) -> str:
    return "*** Begin Patch\n" + "\n".join(sections) + "\n*** End Patch"


def _update(path: str, old: str, new: str) -> str:
    return f"*** Update File: {path}\n@@\n-{old}\n+{new}"


def _event(blob: str, *, event: str = "post_tool_use") -> HookEvent:
    """A Codex `apply_patch` call, normalised by the shipped adapter."""
    return CodexAdapter().parse_hook_input(
        event,
        {
            "session_id": "01a0a301-0d88-7c91-9483-5276101d5acb",
            "cwd": "/private/tmp/codex-step4-wd",
            "hook_event_name": "PreToolUse" if event == "pre_tool_use" else "PostToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": blob},
            "tool_use_id": "call_apply_patch",
        },
        profile=PROFILE,
    )


def test_the_fixture_reaches_both_guards_the_evidence_names() -> None:
    """The precondition every test below rests on, asserted once.

    Without it each test could pass for the wrong reason — a builtin that acts
    on an event carrying neither the operation nor the structure would mean the
    guard under test had been removed, not satisfied.
    """
    tool = _event(_blob(_update("/w/a.py", "x", "y"))).tool
    assert tool is not None
    assert tool.native_name == "apply_patch"
    assert tool.operation is Operation.MODIFY_FILE
    assert len(tool.edits) == 1


def test_format_runs_ruff_on_a_patched_python_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    mod.main(_event(_blob(_update("/w/probe.py", "x   =    1", "x = 1"))))

    assert [c.args[0] for c in fake_run.call_args_list] == [["ruff", "format", "/w/probe.py"]]


def test_ansible_lint_reaches_a_patched_playbook(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as mod

    monkeypatch.setattr(mod, "_lint", lambda path, profile: f"finding on {path}")

    decision = mod.main(_event(_blob(_update("/w/play.yml", "a", "b"))))

    assert decision.additional_context == "finding on /w/play.yml"


def test_sync_claude_regenerates_the_tree_a_patched_segment_belongs_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_claude as mod

    segment = tmp_path / "profiles" / "lazy" / "CLAUDE.head.md"
    segment.parent.mkdir(parents=True)
    segment.write_text("head\n")
    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    mod.main(_event(_blob(_update(str(segment), "head", "HEAD"))))

    fake_sync.assert_called_once()


def test_memory_size_projects_a_patched_file(tmp_path: Path) -> None:
    """The third guard the evidence's two-fix account does not name.

    `_projected_text` branches on the *tool name*: `"Write"` takes `content`,
    `"Edit"` replays `replacements`, and everything else returns `None` and goes
    quiet. So widening `INSPECTED_TOOLS` and parsing the blob still left this
    one builtin silent on `apply_patch` — a third gate, in one builtin only,
    below the two the reconciliation table measures.
    """
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    target = tmp_path / "memory" / "MEMORY.md"
    target.parent.mkdir()
    target.write_text("seed\n" + "x\n" * 10)

    # One replacement line, not 300: a `+` line carrying newlines would not be a
    # patch any more. The breach is bytes, which is the ceiling a curated index
    # of long lines trips first.
    decision = mod.main(
        _event(
            _blob(_update(str(target), "seed", "z" * 20_000)),
            event="pre_tool_use",
        )
    )

    assert "WARN: MEMORY.md" in decision.system_message
    assert decision.verdict is None, "this hook warns; it has never refused"


def test_memory_size_projects_an_added_file(tmp_path: Path) -> None:
    """An `*** Add File:` section is the `Write` shape: the blob *is* the file."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    target = tmp_path / "memory" / "MEMORY.md"
    body = "\n".join(f"+line {i}" for i in range(300))
    blob = f"*** Begin Patch\n*** Add File: {target}\n{body}\n*** End Patch"
    decision = mod.main(_event(blob, event="pre_tool_use"))

    assert "WARN: MEMORY.md" in decision.system_message


def test_a_blob_with_no_file_section_leaves_every_builtin_abstaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The must-fail half: no section parsed, no edit, no action anywhere.

    Paired with the tests above, this is what keeps them from passing on a
    builtin that stopped gating at all: the same tool name and the same
    operation arrive, and only the structure is missing.
    """
    from lazy_harness.hooks.builtins import post_tool_use_ansible_lint as lint
    from lazy_harness.hooks.builtins import post_tool_use_format as fmt
    from lazy_harness.hooks.builtins import post_tool_use_sync_claude as sync
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mem

    fake_run, fake_sync = MagicMock(), MagicMock()
    monkeypatch.setattr(fmt.subprocess, "run", fake_run)
    monkeypatch.setattr(sync, "sync_profiles", fake_sync)
    monkeypatch.setattr(lint, "_lint", lambda path, profile: "should never be reached")

    blob = "*** Begin Patch\n@@\n-a\n+b\n*** End Patch"
    event = _event(blob)
    assert event.tool is not None and event.tool.edits == ()

    assert fmt.main(event) is not None
    fake_run.assert_not_called()
    assert lint.main(event).additional_context == ""
    sync.main(event)
    fake_sync.assert_not_called()
    assert mem.main(_event(blob, event="pre_tool_use")).system_message == ""


# --- one importable answer for "which tool names are an edit" ---------------


def _edit_builtins() -> dict[str, frozenset[str]]:
    import importlib

    return {
        name: importlib.import_module(f"lazy_harness.hooks.builtins.{name}").INSPECTED_TOOLS
        for name in (
            "post_tool_use_format",
            "post_tool_use_sync_claude",
            "post_tool_use_ansible_lint",
            "pre_tool_use_memory_size",
        )
    }


def test_every_edit_builtin_derives_its_tool_set_from_one_place() -> None:
    """Four copies of `frozenset({"Edit", "Write"})` is how three of them got
    fixed for `apply_patch` and the fourth did not. Identity, not equality: an
    equal set that was retyped drifts on the next name."""
    from lazy_harness.hooks.builtins._shared import EDIT_TOOLS

    retyped = [name for name, tools in _edit_builtins().items() if tools is not EDIT_TOOLS]
    assert retyped == [], f"INSPECTED_TOOLS retyped rather than derived by: {retyped}"


def test_the_one_place_names_both_agents_edit_tools() -> None:
    from lazy_harness.hooks.builtins._shared import EDIT_TOOLS

    assert EDIT_TOOLS == frozenset({"Edit", "Write", "apply_patch"})


def test_notebook_edit_stays_out_of_the_edit_set() -> None:
    """Trap 3, still held: `MODIFY_FILE` covers `NotebookEdit` and this set must
    not, or four builtins act on notebooks for the first time."""
    from lazy_harness.hooks.builtins._shared import EDIT_TOOLS

    assert "NotebookEdit" not in EDIT_TOOLS
