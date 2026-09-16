"""Unit tests for pre_tool_use_memory_size hook (ADR-030 G2).

In-process, over `main(event) -> HookDecision`. The byte goldens next door
freeze what the *agent* sees for each branch; these name the decision's own
fields — chiefly that `verdict` stays `None` on every path, including the ones
that speak. `pre_tool_use` honours `DENY`, so a warning that acquired a verdict
would turn an oversized MEMORY.md write into a refused tool call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.agents.base import FileEdit, HookEvent, Operation, ToolCall


def _event(
    file_path: str,
    *,
    tool: str = "Write",
    content: str | None = None,
    replacements: tuple[tuple[str, str], ...] = (),
    replace_all: bool = False,
    profile: str = "p",
) -> HookEvent:
    """One Claude Code edit, already through the adapter's normalisation."""
    return HookEvent(
        event="pre_tool_use",
        profile=profile,
        session_id="s",
        cwd=Path("/nonexistent"),
        transcript_path=None,
        tool=ToolCall(
            native_name=tool,
            operation=Operation.MODIFY_FILE,
            edits=(
                FileEdit(
                    path=Path(file_path),
                    content=content,
                    replacements=replacements,
                    replace_all=replace_all,
                ),
            ),
        ),
    )


MEMORY_PATH = "/home/user/.claude/projects/foo/memory/MEMORY.md"


@pytest.fixture(autouse=True)
def _no_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bypass is an ambient env var; a developer who exported it would
    otherwise turn this whole module green by silencing the hook."""
    monkeypatch.delenv("LH_MEMORY_SIZE_BYPASS", raising=False)


@pytest.fixture(autouse=True)
def _audit_log_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))
    return claude_dir


def test_main_logs_the_warning_to_hooks_log(_audit_log_in_tmp: Path) -> None:
    """The warning goes to the model; the log is what makes it auditable later."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    mod.main(_event(MEMORY_PATH, content="\n".join(f"line {i}" for i in range(300))))

    log = (_audit_log_in_tmp / "logs" / "hooks.log").read_text()
    assert "pre-tool-use-memory-size" in log
    assert "over threshold" in log


def test_the_audit_line_carries_the_breach_and_not_the_remedy(_audit_log_in_tmp: Path) -> None:
    """`hooks.log` is an index of how often this fires, not a copy of the banner.

    The two strings are built separately; deriving the log line from the banner
    by stripping its prefix would append the whole hint to every entry.
    """
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    mod.main(_event(MEMORY_PATH, content="line\n" * 250))

    line = (_audit_log_in_tmp / "logs" / "hooks.log").read_text().strip()
    assert line.endswith(f"over threshold: {MEMORY_PATH} would be 250 lines (threshold 200)")


def test_main_abstains_for_a_tool_this_hook_does_not_inspect() -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    decision = mod.main(_event(MEMORY_PATH, tool="Bash", content="line\n" * 250))

    assert decision.system_message == ""
    assert decision.verdict is None


def test_main_abstains_for_a_notebook_edit_naming_memory_md() -> None:
    """Trap 3: `NotebookEdit` carries `MODIFY_FILE` too, and this hook's
    re-check is a filename — `MEMORY.md` — which a notebook path clears.
    `INSPECTED_TOOLS` is the only narrowing that holds."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    decision = mod.main(_event(MEMORY_PATH, tool="NotebookEdit", content="line\n" * 250))

    assert decision.system_message == ""


def test_main_abstains_when_the_event_carries_no_tool_call() -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    event = HookEvent(
        event="pre_tool_use",
        profile="p",
        session_id="s",
        cwd=Path("/nonexistent"),
        transcript_path=None,
    )

    assert mod.main(event).system_message == ""


def test_main_silent_for_non_memory_md_path() -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    decision = mod.main(_event("/tmp/some-other.md", content="x\n" * 500))

    assert decision.system_message == ""


def test_main_warns_when_write_pushes_memory_md_over_threshold() -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    decision = mod.main(_event(MEMORY_PATH, content="line\n" * 250))

    assert "MEMORY.md" in decision.system_message
    assert "200" in decision.system_message
    assert decision.additional_context == "", (
        "the warning is the only output; an additionalContext carrying nothing "
        "Claude Code reads is noise"
    )


def test_a_warning_is_never_a_verdict() -> None:
    """`pre_tool_use` honours `DENY`. This hook must never reach for it."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    decision = mod.main(_event(MEMORY_PATH, content="line\n" * 250))

    assert decision.system_message
    assert decision.verdict is None
    assert decision.reason == ""
    assert decision.stop is False


def test_main_silent_when_write_keeps_memory_md_under_threshold() -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    assert mod.main(_event(MEMORY_PATH, content="line\n" * 50)).system_message == ""


def test_main_warns_when_edit_pushes_existing_memory_md_over_threshold(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    memory_file = memory_dir / "MEMORY.md"
    memory_file.write_text("existing\n" * 195)

    decision = mod.main(
        _event(
            str(memory_file),
            tool="Edit",
            replacements=(("existing\n", "existing\n" + "new line\n" * 30),),
        )
    )

    assert "MEMORY.md" in decision.system_message
    assert "225 lines" in decision.system_message


def test_replace_all_projects_every_occurrence(tmp_path: Path) -> None:
    """The same edit twice, differing only in the flag: 300 lines against 151."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    memory_file = memory_dir / "MEMORY.md"
    memory_file.write_text("a\n" * 150)

    def project(replace_all: bool) -> str:
        return mod.main(
            _event(
                str(memory_file),
                tool="Edit",
                replacements=(("a\n", "a\na\n"),),
                replace_all=replace_all,
            )
        ).system_message

    assert "300 lines" in project(replace_all=True)
    assert project(replace_all=False) == ""


def test_an_edit_with_no_replacements_projects_the_file_unchanged(tmp_path: Path) -> None:
    """The shape `_projected_text` branches on the tool name to preserve.

    An `Edit` payload carrying no `old_string` normalises to empty
    `replacements`, and the pre-migration code measured the file as it stands
    rather than going quiet. Kept, because byte identity is the acceptance test.
    """
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    memory_file = memory_dir / "MEMORY.md"
    memory_file.write_text("already too long\n" * 250)

    decision = mod.main(_event(str(memory_file), tool="Edit"))

    assert "250 lines" in decision.system_message


def test_bypass_env_var_silences_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    monkeypatch.setenv("LH_MEMORY_SIZE_BYPASS", "1")

    assert mod.main(_event(MEMORY_PATH, content="line\n" * 500)).system_message == ""


def test_main_silent_when_edit_target_does_not_exist(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    nonexistent = tmp_path / "memory" / "MEMORY.md"
    decision = mod.main(_event(str(nonexistent), tool="Edit", replacements=(("x", "y" * 20000),)))

    assert decision.system_message == ""


def test_warns_on_a_file_that_is_small_in_lines_but_large_in_bytes() -> None:
    """The real backstage-poc index was 67 lines and 20KB — it slipped the
    line-count check while being the biggest controllable slice of session
    boot context. Bytes are what the context window pays for."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    fat_index = "\n".join(f"- [note {i}]({i}.md) - {'detail ' * 40}" for i in range(67))

    decision = mod.main(_event(MEMORY_PATH, content=fat_index))

    assert decision.system_message, "a 20KB index must produce a warning even at 67 lines"
    assert "KB" in decision.system_message


def test_main_warns_when_write_pushes_claude_md_over_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLAUDE.md gets its own threshold pair (1a) — same defaults as MEMORY.md
    but a separate config knob and a message naming the right file."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    monkeypatch.delenv("LH_CONFIG_DIR", raising=False)

    decision = mod.main(_event("/repo/CLAUDE.md", content="line\n" * 250))

    assert "CLAUDE.md" in decision.system_message
    assert "200" in decision.system_message
    assert decision.additional_context == ""


def test_main_silent_when_write_keeps_claude_md_under_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    monkeypatch.delenv("LH_CONFIG_DIR", raising=False)

    assert mod.main(_event("/repo/CLAUDE.md", content="line\n" * 50)).system_message == ""


def test_claude_md_threshold_is_configurable_via_config_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """[hooks.pre_tool_use] carries its own claude_md_max_lines/max_bytes,
    separate from MEMORY.md's hardcoded pair."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    config_dir = tmp_path / "lh-config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n[hooks.pre_tool_use]\nclaude_md_max_lines = 10\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(config_dir))

    decision = mod.main(_event("/repo/CLAUDE.md", content="line\n" * 20))

    assert "10" in decision.system_message


def test_claude_md_threshold_falls_back_to_default_on_malformed_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    config_dir = tmp_path / "lh-config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("this is not [ valid toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(config_dir))

    decision = mod.main(_event("/repo/CLAUDE.md", content="line\n" * 250))

    assert "200" in decision.system_message


def test_main_silent_for_a_file_that_merely_ends_in_claude_md() -> None:
    """Out-of-scope near-miss: a file that is not exactly `CLAUDE.md` must not
    be swept in by a loose suffix check."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    assert mod.main(_event("/repo/NOTCLAUDE.md", content="line\n" * 500)).system_message == ""


def test_stays_quiet_for_an_index_that_is_dense_but_within_budget() -> None:
    """The mgmt index — 37 entries, ~6KB — is the shape we want, not a problem."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    lean_index = "\n".join(f"- [note {i}]({i}.md) - {'w' * 120}" for i in range(37))

    assert mod.main(_event(MEMORY_PATH, content=lean_index)).system_message == ""


def test_every_breached_edit_in_one_call_is_reported(tmp_path: Path) -> None:
    """`edits` is plural for the agents whose one call touches several files.

    Claude Code yields at most one, so this shape is unreachable there today —
    but taking `edits[0]` would re-introduce the singular `file_path` assumption
    the contract exists to remove, and nothing else in the suite would notice.
    """
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    over = "line\n" * 250
    event = HookEvent(
        event="pre_tool_use",
        profile="p",
        session_id="s",
        cwd=Path("/nonexistent"),
        transcript_path=None,
        tool=ToolCall(
            native_name="Write",
            operation=Operation.MODIFY_FILE,
            edits=(
                FileEdit(path=Path(MEMORY_PATH), content=over),
                FileEdit(path=Path("/repo/CLAUDE.md"), content=over),
            ),
        ),
    )

    message = mod.main(event).system_message

    assert "MEMORY.md at" in message
    assert "CLAUDE.md at /repo/CLAUDE.md" in message
