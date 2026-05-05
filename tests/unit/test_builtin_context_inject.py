"""Tests for built-in context-inject hook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from lazy_harness.core.config import ProfileEntry
from lazy_harness.hooks.builtins.context_inject import (
    _compose_banner,
    _profile_for_config_dir,
    _strip_intro_lines,
    _truncate_body,
    episodic_context,
    handoff_context,
    last_session_context,
    lazynorth_context,
)


def test_context_inject_returns_json(tmp_path: Path) -> None:
    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "context_inject.py"
    )
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "hookSpecificOutput" in output
    hso = output["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    assert "additionalContext" in hso


def test_context_inject_includes_git_info(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )

    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "context_inject.py"
    )
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    ctx = output["hookSpecificOutput"]["additionalContext"]
    assert "Branch:" in ctx or "branch" in ctx.lower()


def test_last_session_context_picks_most_recent(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    (sessions / "2026-03").mkdir(parents=True)
    (sessions / "2026-04").mkdir(parents=True)
    old = sessions / "2026-03" / "2026-03-01-aaaa.md"
    old.write_text(
        "---\nproject: my-proj\ndate: 2026-03-01 10:00\nmessages: 10\n---\n\n"
        "## User\n\nfirst task\n"
    )
    new = sessions / "2026-04" / "2026-04-10-bbbb.md"
    new.write_text(
        "---\nproject: my-proj\ndate: 2026-04-10 09:00\nmessages: 42\n---\n\n"
        "## User\n\ndebug the broken hook\n"
    )
    import os
    import time

    now = time.time()
    os.utime(old, (now - 3600, now - 3600))
    os.utime(new, (now, now))

    result = last_session_context(sessions, "my-proj")
    assert "2026-04-10 09:00" in result
    assert "42 messages" in result
    assert "debug the broken hook" in result


def test_last_session_context_filters_by_project(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    (sessions / "2026-04").mkdir(parents=True)
    (sessions / "2026-04" / "a.md").write_text(
        "---\nproject: other-proj\ndate: 2026-04-10\nmessages: 1\n---\n\n## User\n\nhi\n"
    )
    assert last_session_context(sessions, "my-proj") == ""


def test_last_session_context_truncates_long_user_message(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    (sessions / "2026-04").mkdir(parents=True)
    long_msg = "a" * 120
    (sessions / "2026-04" / "a.md").write_text(
        f"---\nproject: p\ndate: 2026-04-10\nmessages: 5\n---\n\n## User\n\n{long_msg}\n"
    )
    result = last_session_context(sessions, "p")
    assert '..."' in result


def test_strip_intro_lines_removes_frontmatter_and_h1() -> None:
    text = (
        "---\n"
        "title: test\n"
        "tags: [a]\n"
        "---\n"
        "\n"
        "# Big title\n"
        "Brújula estratégica overview\n"
        "\n"
        "## Principios\n"
        "Content line one\n"
        "Content line two\n"
    )
    out = _strip_intro_lines(text, extra_skip_prefixes=("Brújula estratégica",))
    assert "title: test" not in out
    assert "# Big title" not in "\n".join(out)
    assert any("Brújula estratégica" in line for line in out) is False
    assert "## Principios" in out
    assert "Content line one" in out


def test_lazynorth_context_combines_universal_and_profile(tmp_path: Path) -> None:
    root = tmp_path / "LazyNorth"
    root.mkdir()
    (root / "LazyNorth.md").write_text(
        "---\ntitle: x\n---\n\n# Top\n\n## Principios\n- no1\n- no2\n"
    )
    (root / "LazyNorth-Lazy.md").write_text(
        "---\ntitle: y\n---\n\n# Lazy\n\n## Goals\n- ship harness\n"
    )
    result = lazynorth_context(root, "LazyNorth.md", "LazyNorth-Lazy.md")
    assert "## Principios" in result
    assert "## Goals" in result
    assert "ship harness" in result


def test_lazynorth_context_handles_missing_profile_doc(tmp_path: Path) -> None:
    root = tmp_path / "LazyNorth"
    root.mkdir()
    (root / "LazyNorth.md").write_text("---\n---\n\n## Section\n- point\n")
    result = lazynorth_context(root, "LazyNorth.md", "")
    assert "## Section" in result


def test_lazynorth_context_missing_root(tmp_path: Path) -> None:
    assert lazynorth_context(tmp_path / "nope", "x.md", "") == ""


def test_profile_for_config_dir_matches(tmp_path: Path) -> None:
    lazy_dir = tmp_path / "claude-lazy"
    lazy_dir.mkdir()
    flex_dir = tmp_path / "claude-flex"
    flex_dir.mkdir()
    profiles = {
        "lazy": ProfileEntry(config_dir=str(lazy_dir), lazynorth_doc="LazyNorth-Lazy.md"),
        "flex": ProfileEntry(config_dir=str(flex_dir), lazynorth_doc="LazyNorth-Flex.md"),
    }
    name, doc = _profile_for_config_dir(str(lazy_dir), profiles)
    assert name == "lazy"
    assert doc == "LazyNorth-Lazy.md"

    name, doc = _profile_for_config_dir(str(flex_dir), profiles)
    assert name == "flex"
    assert doc == "LazyNorth-Flex.md"


def test_profile_for_config_dir_no_match() -> None:
    profiles: dict[str, ProfileEntry] = {
        "lazy": ProfileEntry(config_dir="/some/other/path"),
    }
    assert _profile_for_config_dir("/tmp/unknown", profiles) == ("", "")


def test_compose_banner_with_all_parts() -> None:
    git = "Branch: main\nLast commit: abc hello"
    session = 'Last session: 2026-04-10 (42 messages)\nWorking on: "fix bug"'
    handoff = "do stuff"
    banner = _compose_banner(git, session, handoff)
    assert "on main" in banner
    assert "Last session: 2026-04-10 (42 messages)" in banner
    assert "has handoff notes" in banner


def test_compose_banner_empty() -> None:
    assert _compose_banner("", "", "") == "Session context loaded (new project)"


def test_truncate_body_drops_episodic_first() -> None:
    git = "## Git\nbranch"
    north = "## LazyNorth\n" + "n" * 500
    session = "## Last session\nshort"
    handoff = "## Handoff\nh"
    episodic = "## Recent history\n" + "e" * 500

    full = _truncate_body(3000, git, north, session, handoff, episodic)
    assert "## Recent history" in full  # fits under 3000

    trimmed = _truncate_body(800, git, north, session, handoff, episodic)
    assert "## Recent history" not in trimmed
    assert "## LazyNorth" in trimmed


def test_truncate_body_extreme() -> None:
    git = "## Git\nbranch"
    big_north = "## LazyNorth\n" + "n" * 5000
    big_episodic = "## Recent history\n" + "e" * 5000
    result = _truncate_body(100, git, big_north, "", "", big_episodic)
    assert "## Git" in result
    assert "## LazyNorth" not in result


def test_truncate_body_emits_banner_when_episodic_dropped() -> None:
    git = "## Git\nbranch"
    north = "## LazyNorth\n" + "n" * 500
    session = "## Last session\nshort"
    handoff = "## Handoff from last session\nh"
    episodic = "## Recent history\n" + "e" * 500

    result = _truncate_body(800, git, north, session, handoff, episodic)

    first_line = result.splitlines()[0]
    assert first_line.startswith("[truncated:")
    assert "Recent history" in first_line
    assert "800-char budget" in first_line


def test_truncate_body_no_banner_when_body_fits() -> None:
    git = "## Git\nbranch"
    full = _truncate_body(3000, git, "", "", "", "")
    assert not full.startswith("[truncated:")


def test_truncate_body_banner_lists_all_dropped_sections() -> None:
    git = "## Git\nbranch"
    big_north = "## LazyNorth\n" + "n" * 5000
    big_handoff = "## Handoff from last session\n" + "h" * 5000
    big_episodic = "## Recent history\n" + "e" * 5000
    result = _truncate_body(100, git, big_north, "", big_handoff, big_episodic)

    first_line = result.splitlines()[0]
    assert first_line.startswith("[truncated:")
    assert "Recent history" in first_line
    assert "LazyNorth" in first_line
    assert "Handoff from last session" in first_line


def test_handoff_context_from_files(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "handoff.md").write_text("Pendiente:\n- thing 1\n")
    (memory / "pre-compact-summary.md").write_text("<!-- auto -->\n## Tasks\n- resumed work\n")
    result = handoff_context(memory)
    assert "thing 1" in result
    assert "Pre-compact context:" in result
    assert "resumed work" in result
    assert "<!-- auto -->" not in result


def _write_handoff_with_frontmatter(
    memory: Path, session_id: str, source_mtime: float, body_item: str
) -> None:
    memory.mkdir(parents=True, exist_ok=True)
    (memory / "handoff.md").write_text(
        "---\n"
        f"session_id: {session_id}\n"
        f"written_at: 2026-04-12T10:00:00-03:00\n"
        f"source_mtime: {source_mtime:.0f}\n"
        "---\n"
        f"Pendiente para próxima sesión:\n- {body_item}\n"
    )


def test_handoff_context_fresh_session(tmp_path: Path) -> None:
    import os

    encoded = tmp_path / "projects" / "-my-proj"
    memory = encoded / "memory"
    session = encoded / "abcd1234-aaaa-bbbb.jsonl"
    encoded.mkdir(parents=True)
    session.write_text("{}\n")
    os.utime(session, (10_000.0, 10_000.0))
    _write_handoff_with_frontmatter(memory, "abcd1234-aaaa-bbbb", 10_000.0, "do the thing")

    result = handoff_context(memory)
    assert "do the thing" in result
    assert "stale" not in result.lower()


def test_handoff_context_stale_session_id_mismatch(tmp_path: Path) -> None:
    import os

    encoded = tmp_path / "projects" / "-my-proj"
    memory = encoded / "memory"
    newer_session = encoded / "9999abcd-cccc-dddd.jsonl"
    encoded.mkdir(parents=True)
    newer_session.write_text("{}\n")
    os.utime(newer_session, (20_000.0, 20_000.0))
    _write_handoff_with_frontmatter(memory, "abcd1234-aaaa-bbbb", 10_000.0, "old stale item")

    result = handoff_context(memory)
    assert "stale" in result.lower()
    assert "old stale item" in result  # still shown under warning
    assert "9999abcd" in result
    assert "abcd1234" in result


def test_handoff_context_stale_session_grew_past_window(tmp_path: Path) -> None:
    import os

    encoded = tmp_path / "projects" / "-my-proj"
    memory = encoded / "memory"
    session = encoded / "abcd1234-aaaa-bbbb.jsonl"
    encoded.mkdir(parents=True)
    session.write_text("{}\n")
    os.utime(session, (20_000.0, 20_000.0))
    # handoff was written when session mtime was 10_000 — 10k seconds of growth
    _write_handoff_with_frontmatter(memory, "abcd1234-aaaa-bbbb", 10_000.0, "half-done item")

    result = handoff_context(memory)
    assert "stale" in result.lower()
    assert "half-done item" in result


def test_handoff_context_legacy_no_frontmatter(tmp_path: Path) -> None:
    encoded = tmp_path / "projects" / "-my-proj"
    memory = encoded / "memory"
    memory.mkdir(parents=True)
    (memory / "handoff.md").write_text("Pendiente:\n- legacy thing\n")

    result = handoff_context(memory)
    assert "legacy thing" in result
    assert "legacy" in result.lower()


def test_handoff_context_no_file_returns_empty(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    assert handoff_context(memory) == ""


def test_episodic_context_tail(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "decisions.jsonl").write_text(
        json.dumps({"summary": "d1"}) + "\n" + json.dumps({"summary": "d2"}) + "\n"
    )
    (memory / "failures.jsonl").write_text(json.dumps({"summary": "f1", "prevention": "x"}) + "\n")
    result = episodic_context(memory)
    assert "Recent decisions" in result
    assert "- d1" in result
    assert "- d2" in result
    assert "Recent failures" in result
    assert "- f1 → x" in result
