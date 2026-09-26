"""Tests for Claude Code agent adapter."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_claude_adapter_name() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    assert adapter.name == "claude-code"


def test_claude_adapter_config_dir() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter.config_dir("~/.claude-personal")
    assert result == Path.home() / ".claude-personal"


def test_claude_adapter_supported_hooks() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    hooks = adapter.supported_hooks()
    assert "session_start" in hooks
    assert "session_stop" in hooks
    assert "session_end" in hooks
    assert "pre_compact" in hooks


def test_claude_adapter_maps_session_end_to_SessionEnd() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter._generate_hook_config({"session_end": ["lh hook session-end"]})
    assert "SessionEnd" in result
    assert result["SessionEnd"][0]["hooks"][0]["command"] == "lh hook session-end"


def test_registry_get_claude() -> None:
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    assert adapter.name == "claude-code"


def test_registry_unknown_agent() -> None:
    from lazy_harness.agents.registry import AgentNotFoundError, get_agent

    with pytest.raises(AgentNotFoundError):
        get_agent("unknown-agent")


def test_registry_list_agents() -> None:
    from lazy_harness.agents.registry import list_agents

    agents = list_agents()
    assert "claude-code" in agents


def test_claude_adapter_env_var() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().env_var() == "CLAUDE_CONFIG_DIR"


def test_claude_resolve_binary_picks_newest_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    fake_home = tmp_path / "home"
    versions = fake_home / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True)
    older = versions / "2.0.0"
    older.write_text("#!/bin/sh\n")
    older.chmod(0o755)
    newer = versions / "2.1.0"
    newer.write_text("#!/bin/sh\n")
    newer.chmod(0o755)
    # Force newer's mtime to be strictly greater than older's
    os.utime(older, (1_000_000_000, 1_000_000_000))
    os.utime(newer, (2_000_000_000, 2_000_000_000))

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    result = ClaudeCodeAdapter().resolve_binary()
    assert result == newer


def test_claude_resolve_binary_falls_back_to_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents import claude_code as cc_mod
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(cc_mod.shutil, "which", lambda name: "/usr/local/bin/claude")

    result = ClaudeCodeAdapter().resolve_binary()
    assert result == Path("/usr/local/bin/claude")


def test_claude_resolve_binary_returns_none_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents import claude_code as cc_mod
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setattr(cc_mod.shutil, "which", lambda name: None)

    assert ClaudeCodeAdapter().resolve_binary() is None


def _plant_recursive_shim(bin_dir: Path) -> Path:
    """A real `claude` on PATH whose body re-enters `lh run`.

    The thing the recursion warning is about, planted as a file rather than a
    `shutil.which` stub: the guard under test is a path preference, so a stub
    that answers before any path is compared would not exercise it.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "claude"
    shim.write_text('#!/bin/sh\nexec lh run "$@"\n')
    shim.chmod(0o755)
    return shim


def test_a_recursive_claude_shim_on_path_loses_to_the_versioned_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The version-dir preference is the whole recursion guard, so pin it.

    `resolve_binary` is exec'd by `lh run` (`cli/run_cmd.py:101`), so returning
    a wrapper that calls `lh run` is a fork bomb. What prevents it is this
    ordering and nothing else — there is no filter on the PATH candidate.
    """
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    fake_home = tmp_path / "home"
    versions = fake_home / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True)
    real_build = versions / "2.1.0"
    real_build.write_text("#!/bin/sh\n")
    real_build.chmod(0o755)

    shim = _plant_recursive_shim(tmp_path / "bin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("PATH", str(shim.parent))

    assert ClaudeCodeAdapter().resolve_binary() == real_build


def test_a_recursive_claude_shim_is_returned_when_no_versioned_build_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The accepted risk, pinned so it cannot change without the prose changing.

    No filter rejects a PATH candidate that re-enters `lh run`, and adding one
    keyed on the `lh` entrypoint directory would reject the genuine binary:
    `uv tool install` puts `lh` and `claude` in the same `~/.local/bin`.
    """
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    shim = _plant_recursive_shim(tmp_path / "bin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("PATH", str(shim.parent))

    assert ClaudeCodeAdapter().resolve_binary() == shim


def test_generate_hook_config_uses_bash_matcher_for_pre_tool_use() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter._generate_hook_config({"pre_tool_use": ["pre-tool-use-security"]})
    assert "PreToolUse" in result
    entries = result["PreToolUse"]
    assert len(entries) == 1
    assert entries[0]["matcher"] == "Bash"


def test_generate_hook_config_uses_edit_write_matcher_for_post_tool_use() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter._generate_hook_config({"post_tool_use": ["post-tool-use-format"]})
    assert "PostToolUse" in result
    entries = result["PostToolUse"]
    assert len(entries) == 1
    assert entries[0]["matcher"] == "Edit|Write"


def test_generate_hook_config_keeps_empty_matcher_for_other_events() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter._generate_hook_config({"session_start": ["context-inject"]})
    entries = result["SessionStart"]
    assert entries[0]["matcher"] == ""


def test_generate_hook_config_respects_per_script_matcher_override() -> None:
    from lazy_harness.agents.base import HookEntry
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    result = adapter._generate_hook_config(
        {
            "pre_tool_use": [
                HookEntry(command="hook-a", matcher="Edit|Write"),
                "pre-tool-use-security",
            ]
        }
    )
    entries = result["PreToolUse"]
    assert len(entries) == 2
    edit_write = [e for e in entries if e["matcher"] == "Edit|Write"]
    bash = [e for e in entries if e["matcher"] == "Bash"]
    assert len(edit_write) == 1
    assert edit_write[0]["hooks"][0]["command"] == "hook-a"
    assert len(bash) == 1
    assert bash[0]["hooks"][0]["command"] == "pre-tool-use-security"


def test_claude_adapter_generate_mcp_config_returns_dict() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    servers = {
        "qmd": {"command": "qmd", "args": ["mcp"]},
    }
    result = adapter._generate_mcp_config(servers)
    assert isinstance(result, dict)
    assert "mcpServers" in result
    assert "qmd" in result["mcpServers"]
    assert result["mcpServers"]["qmd"]["command"] == "qmd"
    assert result["mcpServers"]["qmd"]["args"] == ["mcp"]


def test_claude_adapter_generate_mcp_config_empty() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter()._generate_mcp_config({})
    assert result == {"mcpServers": {}}


def test_claude_adapter_generate_mcp_config_passes_env() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    servers = {
        "engram": {
            "command": "engram",
            "args": ["mcp"],
            "env": {"ENGRAM_PORT": "7437"},
        },
    }
    result = ClaudeCodeAdapter()._generate_mcp_config(servers)
    assert result["mcpServers"]["engram"]["env"] == {"ENGRAM_PORT": "7437"}


def test_claude_adapter_generate_mcp_config_translates_always_load() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    servers = {
        "graphify": {"command": "graphify-mcp", "args": [], "always_load": True},
        "qmd": {"command": "qmd", "args": ["mcp"]},
    }
    result = ClaudeCodeAdapter()._generate_mcp_config(servers)["mcpServers"]
    assert result["graphify"] == {"command": "graphify-mcp", "args": [], "alwaysLoad": True}
    assert "alwaysLoad" not in result["qmd"]


def test_claude_adapter_owns_no_global_config_link() -> None:
    # `~/.claude` -> profile dir put the profile's CLAUDE.md at `~/.claude/CLAUDE.md`,
    # an ancestor of every repo under $HOME, which stops Claude Code loading any
    # repository AGENTS.md (ADR-060).
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().global_config_link() is None


def test_claude_adapter_default_home_is_the_vendor_directory() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().default_home() == Path.home() / ".claude"


def test_claude_adapter_mcp_config_file() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().mcp_config_file() == ".claude.json"


def test_claude_adapter_session_dirs() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    dirs = ClaudeCodeAdapter().session_dirs()
    assert dirs["sessions"] == "projects"
    assert dirs["logs"] == "logs"
    assert dirs["queue"] == "queue"


def test_claude_adapter_system_docs() -> None:
    from pathlib import Path

    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().system_docs() == [Path("CLAUDE.md")]


def test_claude_adapter_process_name() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().process_name() == "claude"


def test_claude_adapter_supports_user_prompt_submit_and_permission_request() -> None:
    """Events a third-party tool registers on must be modelled, or deploy has
    nowhere to put them and silently drops the entries."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    hooks = ClaudeCodeAdapter().supported_hooks()
    assert "user_prompt_submit" in hooks
    assert "permission_request" in hooks


def test_generate_hook_config_maps_user_prompt_submit_and_permission_request() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter()._generate_hook_config(
        {"user_prompt_submit": ["cmd-a"], "permission_request": ["cmd-b"]}
    )

    assert result["UserPromptSubmit"][0]["hooks"][0]["command"] == "cmd-a"
    assert result["PermissionRequest"][0]["hooks"][0]["command"] == "cmd-b"


def test_generate_hook_config_never_emits_a_null_matcher() -> None:
    """Claude Code validates matcher as a string and discards the whole settings
    file on a null, taking every unrelated hook down with it."""
    from lazy_harness.agents.base import HookEntry
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter()._generate_hook_config(
        {
            "user_prompt_submit": [HookEntry(command="cmd", matcher=None)],
            "session_start": ["cmd"],
        }
    )

    for entries in result.values():
        for entry in entries:
            assert isinstance(entry["matcher"], str)


def test_claude_resolve_binary_skips_a_candidate_whose_interpreter_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Newest mtime does not win when the shebang names an interpreter that is gone.

    Measured on a real machine, not imagined: a 89-byte script left in the
    version dir by a snippet run outside the suite carried the interpreter of a
    git worktree's venv. Its mtime beat the genuine 214MB build by six minutes,
    so both Claude profiles resolved to it; when the worktree was removed,
    `lh run` died with `FileNotFoundError` naming the *script*, because
    `execve` reports a missing interpreter as a missing file.

    The older, valid build is the assertion: a fix that merely refused the
    stale candidate and returned `None` would strand a machine that still has
    a working claude installed.
    """
    import os

    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    fake_home = tmp_path / "home"
    versions = fake_home / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True)

    real_build = versions / "2.1.274"
    real_build.write_text("#!/bin/sh\nexit 0\n")
    real_build.chmod(0o755)

    orphaned = versions / "0.0.1-fake"
    orphaned.write_text(f"#!{tmp_path / 'removed-worktree' / '.venv' / 'bin' / 'python3'}\npass\n")
    orphaned.chmod(0o755)

    os.utime(real_build, (1_000_000_000, 1_000_000_000))
    os.utime(orphaned, (2_000_000_000, 2_000_000_000))

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    assert ClaudeCodeAdapter().resolve_binary() == real_build
