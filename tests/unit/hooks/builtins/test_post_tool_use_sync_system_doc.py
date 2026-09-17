"""Unit tests for post_tool_use_sync_system_doc hook."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lazy_harness.agents.base import FileEdit, HookEvent, Operation, ToolCall


def _event(tool: str | None, path: str | None, *, profile: str = "p") -> HookEvent:
    """One PostToolUse invocation, in the shape the adapter normalises to.

    `operation` is set from the tool name the way `_TOOL_OPERATIONS` does it, so
    that a gate reading the operation rather than the name is exercised by the
    same fixtures — which is what makes the `NotebookEdit` case below a witness
    rather than a restatement of the gate it tests.
    """
    call: ToolCall | None = None
    if tool is not None:
        operation = {
            "Edit": Operation.MODIFY_FILE,
            "Write": Operation.MODIFY_FILE,
            "NotebookEdit": Operation.MODIFY_FILE,
            "Read": Operation.READ_FILE,
        }.get(tool)
        edits = (FileEdit(path=Path(path)),) if path and operation is Operation.MODIFY_FILE else ()
        reads = (Path(path),) if path and operation is Operation.READ_FILE else ()
        call = ToolCall(native_name=tool, operation=operation, edits=edits, reads=reads)
    return HookEvent(
        event="post_tool_use",
        profile=profile,
        session_id="s1",
        cwd=Path("/work"),
        transcript_path=None,
        tool=call,
    )


@pytest.fixture(autouse=True)
def _no_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point config resolution at an empty dir — a machine with no config.toml.

    Without this the hook reads whatever config the developer happens to have,
    so the suite only ever exercised the configured path.
    """
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path / "config"))


def test_triggers_on_head_edit_under_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    decision = mod.main(_event("Edit", "/x/.config/lazy-harness/profiles/lazy/CLAUDE.head.md"))

    assert decision.verdict is None
    fake_sync.assert_called_once()
    args = fake_sync.call_args[0]
    assert args[0] == Path("/x/.config/lazy-harness/profiles")
    # No config.toml → fall back to the default adapter rather than skipping.
    assert args[1].name == "claude-code"


def test_triggers_on_tail_write_under_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    mod.main(_event("Write", "/x/.config/lazy-harness/profiles/flex/CLAUDE.tail.md"))

    fake_sync.assert_called_once()


def test_triggers_on_common_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    mod.main(_event("Edit", "/x/.config/lazy-harness/profiles/_common/CLAUDE.common.md"))

    fake_sync.assert_called_once()


def test_skips_unrelated_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    decision = mod.main(_event("Edit", "/x/.config/lazy-harness/profiles/lazy/settings.json"))

    assert decision.verdict is None
    fake_sync.assert_not_called()


def test_skips_non_edit_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    mod.main(_event("Read", "/x/.config/lazy-harness/profiles/lazy/CLAUDE.head.md"))

    fake_sync.assert_not_called()


def test_skips_a_notebook_edit_even_when_it_is_named_like_a_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Trap 3: `MODIFY_FILE` is wider than `INSPECTED_TOOLS` by `NotebookEdit`.

    The second gate is a filename match, not an extension, so the `.ipynb`
    assumption that made the widening look inert does not hold here: a notebook
    whose normalised path is named `CLAUDE.head.md` clears it. This fails the
    moment the tool-name gate is replaced by `event.tool.operation`.
    """
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    event = _event("NotebookEdit", "/x/.config/lazy-harness/profiles/lazy/CLAUDE.head.md")
    assert event.tool is not None
    assert event.tool.operation is Operation.MODIFY_FILE, "fixture must reach the widened gate"

    mod.main(event)

    fake_sync.assert_not_called()


def test_skips_segment_outside_profiles_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `CLAUDE.head.md` outside a `profiles/<name>/` tree must not trigger."""
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    decision = mod.main(_event("Edit", "/some/other/repo/CLAUDE.head.md"))

    assert decision.verdict is None
    fake_sync.assert_not_called()


def test_skips_an_edit_carrying_no_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    mod.main(_event("Edit", None))

    fake_sync.assert_not_called()


def test_skips_an_event_carrying_no_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ToolCall` is optional on `HookEvent`, so the gate has to survive `None`."""
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock()
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    decision = mod.main(_event(None, None))

    assert decision.verdict is None
    fake_sync.assert_not_called()


def test_syncs_every_distinct_tree_a_multi_file_edit_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ToolCall.edits` is plural, and reading only the first would drop the rest.

    Claude Code never delivers more than one edit per call, so this is inert
    against today's adapter — which is the point: the singular assumption
    belongs in the adapter that knows it holds, not in the hook.
    """
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    event = _event("Edit", None)
    assert event.tool is not None
    multi = ToolCall(
        native_name="Edit",
        operation=Operation.MODIFY_FILE,
        edits=(
            FileEdit(path=Path("/a/profiles/lazy/CLAUDE.head.md")),
            FileEdit(path=Path("/a/profiles/flex/CLAUDE.tail.md")),
            FileEdit(path=Path("/b/profiles/lazy/CLAUDE.head.md")),
            FileEdit(path=Path("/b/profiles/lazy/README.md")),
        ),
    )
    mod.main(
        HookEvent(
            event="post_tool_use",
            profile="p",
            session_id="s1",
            cwd=Path("/work"),
            transcript_path=None,
            tool=multi,
        )
    )

    assert [call[0][0] for call in fake_sync.call_args_list] == [
        Path("/a/profiles"),
        Path("/b/profiles"),
    ]


def test_a_deleted_segment_regenerates_its_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-046 D4 — the one reader that *gains* from the widening.

    A segment removed from a profile tree changes the document assembled from
    it exactly as an edited one does. Before `ToolCall.deletes` existed the
    removal produced no `FileEdit` at all, so the deployed contract file went
    stale with nothing on any channel saying so.
    """
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    call = ToolCall(
        native_name="apply_patch",
        operation=Operation.MODIFY_FILE,
        deletes=(Path("/a/profiles/_common/codex.md"),),
    )
    mod.main(
        HookEvent(
            event="post_tool_use",
            profile="p",
            session_id="s1",
            cwd=Path("/work"),
            transcript_path=None,
            tool=call,
        )
    )

    assert [c[0][0] for c in fake_sync.call_args_list] == [Path("/a/profiles")]


def test_a_deleted_file_that_is_no_segment_still_syncs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The must-fail half of the test above. Reading `deletes` must not widen
    the *filename* gate: a tree is regenerated because a segment moved, and a
    delete of anything else under `profiles/` is not that."""
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    call = ToolCall(
        native_name="apply_patch",
        operation=Operation.MODIFY_FILE,
        deletes=(Path("/a/profiles/lazy/notes.md"),),
    )
    mod.main(
        HookEvent(
            event="post_tool_use",
            profile="p",
            session_id="s1",
            cwd=Path("/work"),
            transcript_path=None,
            tool=call,
        )
    )

    fake_sync.assert_not_called()


def test_one_call_editing_and_deleting_syncs_both_trees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mixed blob probe 5 measured, with a delete in it. The two collections
    are read in order — edits then deletes — and neither shadows the other."""
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    call = ToolCall(
        native_name="apply_patch",
        operation=Operation.MODIFY_FILE,
        edits=(FileEdit(path=Path("/a/profiles/lazy/CLAUDE.head.md")),),
        deletes=(Path("/b/profiles/_common/codex.md"),),
    )
    mod.main(
        HookEvent(
            event="post_tool_use",
            profile="p",
            session_id="s1",
            cwd=Path("/work"),
            transcript_path=None,
            tool=call,
        )
    )

    assert [c[0][0] for c in fake_sync.call_args_list] == [
        Path("/a/profiles"),
        Path("/b/profiles"),
    ]


def test_swallows_sync_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """If sync_profiles raises, the hook still abstains — never block the agent."""
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    def boom(*_: object, **__: object) -> object:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(mod, "sync_profiles", boom)

    decision = mod.main(_event("Edit", "/x/.config/lazy-harness/profiles/lazy/CLAUDE.head.md"))

    assert decision.verdict is None
    assert decision.system_message == ""
    assert decision.additional_context == ""


def test_resolves_the_adapter_of_the_invoked_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`event.profile`, not the global `[agent].type`.

    The integration counterpart drives the real CLI and asserts on the file
    that gets regenerated; this one names the adapter directly, so a change
    that kept writing the right file for the wrong reason still fails here.
    """
    from lazy_harness.hooks.builtins import post_tool_use_sync_system_doc as mod

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[harness]\nversion = '1'\n\n[agent]\ntype = 'claude-code'\n\n"
        "[profiles]\ndefault = 'lazy'\n\n"
        f"[profiles.lazy]\nconfig_dir = '{tmp_path / 'lazy'}'\n\n"
        f"[profiles.other]\nconfig_dir = '{tmp_path / 'other'}'\nagent = 'codex'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(config_dir))
    fake_sync = MagicMock(return_value=[])
    monkeypatch.setattr(mod, "sync_profiles", fake_sync)

    mod.main(
        _event("Edit", "/x/.config/lazy-harness/profiles/lazy/CLAUDE.head.md", profile="other")
    )

    assert fake_sync.call_args[0][1].name == "codex"
