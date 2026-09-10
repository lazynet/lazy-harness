"""Unit tests for pre_tool_use_memory_size hook (ADR-030 G2)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest


def test_main_logs_the_warning_to_hooks_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The warning goes to the model; the log is what makes it auditable later."""
    import io

    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))
    monkeypatch.delenv("LH_MEMORY_SIZE_BYPASS", raising=False)

    memory_md = tmp_path / "memory" / "MEMORY.md"
    memory_md.parent.mkdir(parents=True)
    memory_md.write_text("x\n")

    payload = json.dumps(
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(memory_md),
                "content": "\n".join(f"line {i}" for i in range(300)),
            },
        }
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    with pytest.raises(SystemExit):
        mod.main()

    log = (claude_dir / "logs" / "hooks.log").read_text()
    assert "pre-tool-use-memory-size" in log
    assert "over threshold" in log


def test_main_exits_zero_for_non_edit_write_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    monkeypatch.setattr("sys.stdin", io.StringIO('{"tool_name": "Bash", "tool_input": {}}'))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0


def test_main_silent_for_non_memory_md_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/tmp/some-other.md",
            "content": "x\n" * 500,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_main_warns_when_write_pushes_memory_md_over_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/home/user/.claude/projects/foo/memory/MEMORY.md",
            "content": "line\n" * 250,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "MEMORY.md" in output["hookSpecificOutput"]["systemMessage"]
    assert "200" in output["hookSpecificOutput"]["systemMessage"]


def test_main_silent_when_write_keeps_memory_md_under_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/home/user/.claude/projects/foo/memory/MEMORY.md",
            "content": "line\n" * 50,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_main_warns_when_edit_pushes_existing_memory_md_over_threshold(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    memory_file = memory_dir / "MEMORY.md"
    memory_file.write_text("existing\n" * 195)

    big_addition = "new line\n" * 30
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(memory_file),
            "old_string": "existing\n",
            "new_string": "existing\n" + big_addition,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert captured.out, "expected warning JSON on stdout"
    output = json.loads(captured.out)
    assert "MEMORY.md" in output["hookSpecificOutput"]["systemMessage"]


def test_bypass_env_var_silences_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/home/user/.claude/projects/foo/memory/MEMORY.md",
            "content": "line\n" * 500,
        },
    }
    monkeypatch.setenv("LH_MEMORY_SIZE_BYPASS", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_main_silent_when_edit_target_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    nonexistent = tmp_path / "memory" / "MEMORY.md"
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(nonexistent),
            "old_string": "x",
            "new_string": "y",
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_warns_on_a_file_that_is_small_in_lines_but_large_in_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real backstage-poc index was 67 lines and 20KB — it slipped the
    line-count check while being the biggest controllable slice of session
    boot context. Bytes are what the context window pays for."""
    import io

    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.delenv("LH_MEMORY_SIZE_BYPASS", raising=False)

    memory_md = tmp_path / "memory" / "MEMORY.md"
    memory_md.parent.mkdir(parents=True)
    memory_md.write_text("x\n")

    # 67 lines of ~300 bytes: well under 200 lines, well over the byte ceiling.
    fat_index = "\n".join(f"- [note {i}]({i}.md) — {'detail ' * 40}" for i in range(67))
    payload = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": str(memory_md), "content": fat_index}}
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)

    with pytest.raises(SystemExit):
        mod.main()

    warning = out.getvalue()
    assert warning, "a 20KB index must produce a warning even at 67 lines"
    assert "KB" in warning or "bytes" in warning


def test_main_warns_when_write_pushes_claude_md_over_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLAUDE.md gets its own threshold pair (1a) — same defaults as MEMORY.md
    but a separate config knob and a message naming the right file."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    monkeypatch.delenv("LH_CONFIG_DIR", raising=False)
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/CLAUDE.md",
            "content": "line\n" * 250,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "CLAUDE.md" in output["hookSpecificOutput"]["systemMessage"]
    assert "200" in output["hookSpecificOutput"]["systemMessage"]


def test_main_silent_when_write_keeps_claude_md_under_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    monkeypatch.delenv("LH_CONFIG_DIR", raising=False)
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/CLAUDE.md",
            "content": "line\n" * 50,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_claude_md_threshold_is_configurable_via_config_toml(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
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

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/CLAUDE.md",
            "content": "line\n" * 20,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "10" in output["hookSpecificOutput"]["systemMessage"]


def test_claude_md_threshold_falls_back_to_default_on_malformed_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    config_dir = tmp_path / "lh-config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("this is not [ valid toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(config_dir))

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/CLAUDE.md",
            "content": "line\n" * 250,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "200" in output["hookSpecificOutput"]["systemMessage"]


def test_main_silent_for_a_file_that_merely_ends_in_claude_md(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Out-of-scope near-miss: a file that is not exactly `CLAUDE.md` must not
    be swept in by a loose suffix check."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/repo/NOTCLAUDE.md",
            "content": "line\n" * 500,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("raw_payload", ["null", "42", "[]", '"a string"'])
def test_main_exits_zero_for_wrong_type_json_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], raw_payload: str
) -> None:
    """Valid JSON that parses to something other than an object must not crash
    the hook — Claude Code's payload contract is a dict, but a malformed or
    unexpected invocation must still degrade to a silent exit 0."""
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    monkeypatch.setattr("sys.stdin", io.StringIO(raw_payload))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_main_exits_zero_when_tool_input_is_not_a_dict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {"tool_name": "Write", "tool_input": ["not", "a", "dict"]}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_main_exits_zero_when_file_path_is_not_a_string(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {"tool_name": "Write", "tool_input": {"file_path": 12345, "content": "x"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_stays_quiet_for_an_index_that_is_dense_but_within_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The mgmt index — 37 entries, ~6KB — is the shape we want, not a problem."""
    import io

    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.delenv("LH_MEMORY_SIZE_BYPASS", raising=False)

    memory_md = tmp_path / "memory" / "MEMORY.md"
    memory_md.parent.mkdir(parents=True)
    memory_md.write_text("x\n")

    lean_index = "\n".join(f"- [note {i}]({i}.md) — {'w' * 120}" for i in range(37))
    payload = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": str(memory_md), "content": lean_index}}
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)

    with pytest.raises(SystemExit):
        mod.main()

    assert out.getvalue() == ""
