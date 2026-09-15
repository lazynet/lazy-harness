"""Tests for built-in session-export hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_session_export_hook_exits_zero(tmp_path: Path) -> None:
    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "session_export.py"
    )
    session_file = tmp_path / "projects" / "-tmp-test" / "abc12345.jsonl"
    session_file.parent.mkdir(parents=True)
    messages = [
        {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
        {"type": "system", "cwd": "/tmp/test", "timestamp": "2026-04-12T10:00:00"},
        {
            "type": "user",
            "message": {"content": "first question here"},
            "timestamp": "2026-04-12T10:00:01",
        },
        {
            "type": "assistant",
            "message": {"content": "first answer here"},
            "timestamp": "2026-04-12T10:00:02",
        },
        {
            "type": "user",
            "message": {"content": "second question"},
            "timestamp": "2026-04-12T10:00:03",
        },
        {
            "type": "assistant",
            "message": {"content": "second answer"},
            "timestamp": "2026-04-12T10:00:04",
        },
    ]
    session_file.write_text("\n".join(json.dumps(m) for m in messages) + "\n")
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(tmp_path),
        "LH_KNOWLEDGE_DIR": str(knowledge_dir),
    }
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd="/tmp/test" if Path("/tmp/test").exists() else str(tmp_path),
        timeout=15,
        env=env,
    )
    assert result.returncode == 0


def test_session_export_routes_paths_through_agent_adapter(tmp_path: Path, monkeypatch) -> None:
    """ADR-032 L3/L4: the sessions dir must come from the configured agent
    adapter, not from a hardcoded CLAUDE_CONFIG_DIR read. With agent.type =
    "null" resolution must land under ~/.null even when CLAUDE_CONFIG_DIR
    points elsewhere."""
    import io

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    decoy_dir = tmp_path / "decoy-claude"

    cwd = tmp_path / "proj"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = home / ".null" / "projects" / encoded
    sessions_dir.mkdir(parents=True)
    session_file = sessions_dir / "abc12345.jsonl"
    messages = [
        {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
        {"type": "system", "cwd": str(cwd), "timestamp": "2026-04-12T10:00:00"},
        {
            "type": "user",
            "message": {"content": "a" * 250},
            "timestamp": "2026-04-12T10:00:01",
        },
        {
            "type": "assistant",
            "message": {"content": "first answer here"},
            "timestamp": "2026-04-12T10:00:02",
        },
        {
            "type": "user",
            "message": {"content": "second question"},
            "timestamp": "2026-04-12T10:00:03",
        },
        {
            "type": "assistant",
            "message": {"content": "second answer"},
            "timestamp": "2026-04-12T10:00:04",
        },
    ]
    session_file.write_text("\n".join(json.dumps(m) for m in messages) + "\n")

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'
    )
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f"""
[harness]
version = "1"

[agent]
type = "null"

[knowledge]
root = "{knowledge_dir}"
"""
    )
    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import session_export as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(decoy_dir))
    monkeypatch.chdir(cwd)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    monkeypatch.setattr(hook_mod.shutil, "which", lambda _: None)
    hook_mod.main()

    exported = list((knowledge_dir / "sessions").rglob("*.md"))
    assert len(exported) == 1


def test_session_export_keeps_the_declared_project_dir_when_the_transcript_is_unwritten(
    tmp_path: Path, monkeypatch
) -> None:
    """The declared path reaches `resolve_project_dir` un-stat'd, and must.

    `existing_transcript` filters a transcript that is not on disk yet;
    `resolve_project_dir` only stats the *parent*, so it still recovers the
    project dir the agent named. Passing the filtered value to both — the one
    swap this refactor makes easy — silently discards the agent's own naming
    and falls back to encoding the cwd, which is a different directory.

    Asserted by running the hook rather than by watching an argument: the two
    directories hold different sessions, so only the right one exports.
    """
    import io

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    cwd = tmp_path / "proj"
    cwd.mkdir()
    sessions_root = home / ".null" / "projects"

    # What the agent named. Deliberately not re-derivable from the cwd.
    declared_dir = sessions_root / "-agent-chose-this-name"
    declared_dir.mkdir(parents=True)
    session_file = declared_dir / "abc12345.jsonl"
    session_file.write_text(
        "\n".join(
            json.dumps(m)
            for m in (
                {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
                {"type": "system", "cwd": str(cwd), "timestamp": "2026-04-12T10:00:00"},
                {
                    "type": "user",
                    "message": {"content": "b" * 250},
                    "timestamp": "2026-04-12T10:00:01",
                },
                {
                    "type": "assistant",
                    "message": {"content": "answer from the declared dir"},
                    "timestamp": "2026-04-12T10:00:02",
                },
                {
                    "type": "user",
                    "message": {"content": "second question"},
                    "timestamp": "2026-04-12T10:00:03",
                },
                {
                    "type": "assistant",
                    "message": {"content": "second answer"},
                    "timestamp": "2026-04-12T10:00:04",
                },
            )
        )
        + "\n"
    )

    # Where encoding the cwd would land instead: present, and empty.
    (sessions_root / ("-" + str(cwd).replace("/", "-").lstrip("-"))).mkdir(parents=True)

    # Declared on stdin, never written to disk.
    unwritten = declared_dir / "0197f0de-cafe-4bad-9001-000000000007.jsonl"
    assert not unwritten.exists()

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'
    )
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f'''
[harness]
version = "1"

[agent]
type = "null"

[knowledge]
root = "{knowledge_dir}"
'''
    )

    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import session_export as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)
    monkeypatch.chdir(cwd)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"transcript_path": str(unwritten)})))
    monkeypatch.setattr(hook_mod.shutil, "which", lambda _: None)
    hook_mod.main()

    exported = list((knowledge_dir / "sessions").rglob("*.md"))
    assert len(exported) == 1, "the declared project dir was not searched"
    assert "answer from the declared dir" in exported[0].read_text()


def test_session_export_registered() -> None:
    from lazy_harness.hooks.loader import list_builtin_hooks

    assert "session-export" in list_builtin_hooks()
