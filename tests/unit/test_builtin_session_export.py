"""Tests for built-in session-export hook.

`main` takes a `HookEvent` and returns a `HookDecision`, so these call it
directly rather than driving a subprocess over stdin. The three channels the
agent actually reads are frozen in
`tests/unit/hooks/builtins/test_session_export_goldens.py`, which runs the
deployed command end to end; what is left here is path resolution, which is
cheaper and clearer to assert against the function.

Retired with the migration: `test_session_export_hook_exits_zero`, which ran
`python <path>` and asserted `returncode == 0`. A migrated builtin is never
invoked as a bare script — `main()` would fail on the missing argument — and
the assertion it carried is now made seven times over, once per golden.
"""

from __future__ import annotations

import json
from pathlib import Path

from lazy_harness.agents.base import HookEvent

KNOWLEDGE_MARKER = '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'


def _event(cwd: Path, transcript: Path | None = None) -> HookEvent:
    return HookEvent(
        event="session_stop",
        profile="",
        session_id="abc12345",
        cwd=cwd,
        transcript_path=transcript,
    )


def _messages(cwd: Path, answer: str) -> str:
    return (
        "\n".join(
            json.dumps(m)
            for m in (
                {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
                {"type": "system", "cwd": str(cwd), "timestamp": "2026-04-12T10:00:00"},
                {
                    "type": "user",
                    "message": {"content": "a" * 250},
                    "timestamp": "2026-04-12T10:00:01",
                },
                {
                    "type": "assistant",
                    "message": {"content": answer},
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


def _knowledge_store(tmp_path: Path) -> Path:
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "knowledge.toml").write_text(KNOWLEDGE_MARKER)
    return knowledge_dir


def _null_agent_config(tmp_path: Path, knowledge_dir: Path) -> Path:
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
    return cfg_file


def test_session_export_routes_paths_through_agent_adapter(tmp_path: Path, monkeypatch) -> None:
    """ADR-032 L3/L4: the sessions dir must come from the configured agent
    adapter, not from a hardcoded CLAUDE_CONFIG_DIR read. With agent.type =
    "null" resolution must land under ~/.null even when CLAUDE_CONFIG_DIR
    points elsewhere."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    decoy_dir = tmp_path / "decoy-claude"

    cwd = tmp_path / "proj"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = home / ".null" / "projects" / encoded
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "abc12345.jsonl").write_text(_messages(cwd, "first answer here"))

    knowledge_dir = _knowledge_store(tmp_path)
    cfg_file = _null_agent_config(tmp_path, knowledge_dir)

    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import session_export as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(decoy_dir))
    monkeypatch.setattr(hook_mod.shutil, "which", lambda _: None)

    hook_mod.main(_event(cwd))

    exported = list((knowledge_dir / "sessions").rglob("*.md"))
    assert len(exported) == 1
    assert not decoy_dir.exists()


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
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    cwd = tmp_path / "proj"
    cwd.mkdir()
    sessions_root = home / ".null" / "projects"

    # What the agent named. Deliberately not re-derivable from the cwd.
    declared_dir = sessions_root / "-agent-chose-this-name"
    declared_dir.mkdir(parents=True)
    (declared_dir / "abc12345.jsonl").write_text(_messages(cwd, "answer from the declared dir"))

    # Where encoding the cwd would land instead: present, and empty.
    (sessions_root / ("-" + str(cwd).replace("/", "-").lstrip("-"))).mkdir(parents=True)

    # Declared on the event, never written to disk.
    unwritten = declared_dir / "0197f0de-cafe-4bad-9001-000000000007.jsonl"
    assert not unwritten.exists()

    knowledge_dir = _knowledge_store(tmp_path)
    cfg_file = _null_agent_config(tmp_path, knowledge_dir)

    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import session_export as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)
    monkeypatch.setattr(hook_mod.shutil, "which", lambda _: None)

    hook_mod.main(_event(cwd, transcript=unwritten))

    exported = list((knowledge_dir / "sessions").rglob("*.md"))
    assert len(exported) == 1, "the declared project dir was not searched"
    assert "answer from the declared dir" in exported[0].read_text()


def test_session_export_abstains_on_every_branch(tmp_path: Path, monkeypatch) -> None:
    """No verdict, ever. A Stop hook that returned one would stop the session.

    Exercised on the earliest branch — no config file — because that is the one
    a future edit is most likely to turn into a refusal by reflex.
    """
    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import session_export as hook_mod

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(paths_mod, "config_file", lambda: tmp_path / "absent.toml")

    decision = hook_mod.main(_event(tmp_path))

    assert decision.verdict is None
    assert decision.stop is False
    assert decision.additional_context == ""
    assert decision.system_message == ""


def test_session_export_registered() -> None:
    from lazy_harness.hooks.loader import list_builtin_hooks

    assert "session-export" in list_builtin_hooks()
