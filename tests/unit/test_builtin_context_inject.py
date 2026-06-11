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
    proposals_context,
    proposals_summary_line,
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


def test_context_inject_config_qmd_suggest_defaults() -> None:
    from lazy_harness.core.config import ContextInjectConfig

    cfg = ContextInjectConfig()
    assert cfg.qmd_suggest_enabled is True
    assert cfg.qmd_suggest_top_k == 3


def test_context_inject_config_graphify_surface_default_is_true() -> None:
    from lazy_harness.core.config import ContextInjectConfig

    cfg = ContextInjectConfig()
    assert cfg.graphify_surface_enabled is True


def test_context_inject_includes_graphify_summary_when_graph_is_fresh(
    tmp_path: Path,
) -> None:
    """Black-box: hook subprocess sees a fresh graph.json and emits the summary."""
    import os as _os
    import time as _time

    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        env={
            **_os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "x", "community": 0},
                    {"id": "y", "community": 0},
                    {"id": "z", "community": 1},
                ],
                "edges": [],
            }
        )
    )
    fresh_ts = _time.time() + 5
    _os.utime(out / "graph.json", (fresh_ts, fresh_ts))

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
    ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "## Code structure" in ctx
    assert "3 nodes" in ctx


def test_qmd_suggest_context_returns_empty_when_no_hits(monkeypatch) -> None:
    from lazy_harness.hooks.builtins import context_inject as mod

    monkeypatch.setattr("lazy_harness.knowledge.qmd.query", lambda *a, **kw: [])
    assert mod.qmd_suggest_context("anything", top_k=3) == ""


def test_qmd_suggest_context_formats_hits_as_markdown(monkeypatch) -> None:
    from lazy_harness.hooks.builtins import context_inject as mod
    from lazy_harness.knowledge.qmd import QmdHit

    hits = [
        QmdHit(file="qmd://col/a.md", title="Auth notes", score=0.91),
        QmdHit(file="qmd://col/b.md", title="OAuth flow", score=0.87),
    ]
    monkeypatch.setattr("lazy_harness.knowledge.qmd.query", lambda *a, **kw: hits)
    out = mod.qmd_suggest_context("auth", top_k=3)
    assert "Auth notes" in out
    assert "OAuth flow" in out
    assert "qmd://col/a.md" in out


def test_qmd_suggest_context_returns_empty_for_blank_query(monkeypatch) -> None:
    from lazy_harness.hooks.builtins import context_inject as mod

    called = {"n": 0}

    def fake_query(*a, **kw):
        called["n"] += 1
        return []

    monkeypatch.setattr("lazy_harness.knowledge.qmd.query", fake_query)
    assert mod.qmd_suggest_context("", top_k=3) == ""
    assert called["n"] == 0


def test_graphify_section_returns_empty_when_graph_missing(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins.context_inject import graphify_section

    assert graphify_section(tmp_path / "no-such-out", tmp_path) == ""


def test_graphify_section_emits_staleness_banner_when_graph_older_than_head(
    tmp_path: Path,
) -> None:
    import os as _os
    import time as _time

    from lazy_harness.hooks.builtins.context_inject import graphify_section

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(repo),
        capture_output=True,
        env={
            **_os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    out = repo / "graphify-out"
    out.mkdir()
    graph = out / "graph.json"
    graph.write_text(json.dumps({"nodes": [], "edges": []}))
    old_ts = _time.time() - 86400
    _os.utime(graph, (old_ts, old_ts))

    section = graphify_section(out, repo)
    assert "stale" in section.lower()
    assert "/graphify" in section


def test_graphify_section_emits_content_summary_when_fresh(tmp_path: Path) -> None:
    import os as _os
    import time as _time

    from lazy_harness.hooks.builtins.context_inject import graphify_section

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(repo),
        capture_output=True,
        env={
            **_os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    out = repo / "graphify-out"
    out.mkdir()
    graph = out / "graph.json"
    nodes = (
        [{"id": f"n{i}", "community": 0, "source_file": "a.py"} for i in range(5)]
        + [{"id": f"n{i + 100}", "community": 1, "source_file": "b.py"} for i in range(3)]
        + [{"id": f"n{i + 200}", "community": 2, "source_file": "c.py"} for i in range(2)]
    )
    graph.write_text(json.dumps({"nodes": nodes, "edges": []}))
    fresh_ts = _time.time() + 5
    _os.utime(graph, (fresh_ts, fresh_ts))

    section = graphify_section(out, repo)
    assert "Code structure" in section
    assert "10 nodes" in section
    assert "3 communities" in section


def test_truncate_body_includes_suggest_section_when_body_fits() -> None:
    git = "## Git\nbranch"
    suggest = "## Relevant vault notes\n- [a](qmd://a.md)"
    episodic = "## Recent history\nrecent"

    full = _truncate_body(3000, git, "", "", "", episodic, suggest_section=suggest)
    assert "## Relevant vault notes" in full
    assert "## Recent history" in full
    # Order: suggest before episodic per ADR-030 G3
    assert full.index("## Relevant vault notes") < full.index("## Recent history")


def test_context_inject_includes_qmd_suggest_section_when_qmd_returns_hits(
    tmp_path: Path,
) -> None:
    """Black-box: hook subprocess sees a fake qmd in PATH and surfaces results."""
    import os as _os

    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        env={
            **_os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )

    bin_dir = tmp_path / "fake_bin"
    bin_dir.mkdir()
    fake_qmd = bin_dir / "qmd"
    fake_qmd.write_text(
        "#!/usr/bin/env bash\n"
        'echo \'[{"file": "qmd://col/a.md", "title": "Auth notes", "score": 0.9}]\'\n'
    )
    fake_qmd.chmod(0o755)

    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "context_inject.py"
    )
    env = {**_os.environ, "PATH": f"{bin_dir}:{_os.environ['PATH']}"}
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
        env=env,
    )
    assert result.returncode == 0
    ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "## Relevant vault notes" in ctx
    assert "Auth notes" in ctx


def test_truncate_body_drops_episodic_before_suggest() -> None:
    git = "## Git\nb"
    suggest = "## Relevant vault notes\n" + "v" * 100
    episodic = "## Recent history\n" + "e" * 1000

    trimmed = _truncate_body(300, git, "", "", "", episodic, suggest_section=suggest)
    assert "## Recent history" not in trimmed
    assert "## Relevant vault notes" in trimmed
    assert trimmed.startswith("[truncated:")


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


def test_proposals_context_reads_file_stripping_html_comment(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "claude-md.proposal.md").write_text(
        "<!-- claude-md proposals (append-only). Review and merge into CLAUDE.md or discard. -->\n"
        "\n"
        "## 2026-05-20T10:00:00-03:00\n"
        "\n"
        "- **Rule:** Always use os.replace for iCloud-synced paths\n"
        "  - **Rationale:** Non-atomic writes cause conflict copies\n"
    )

    result = proposals_context(memory)

    assert "Always use os.replace for iCloud-synced paths" in result
    assert "Non-atomic writes cause conflict copies" in result
    assert "claude-md proposals (append-only)" not in result


def test_proposals_context_no_file_returns_empty(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    assert proposals_context(memory) == ""


def test_context_inject_surfaces_proposals_section_in_stdout(tmp_path: Path) -> None:
    encoded = "-" + str(tmp_path).replace("/", "-").lstrip("-")
    claude_dir = tmp_path / ".claude"
    memory = claude_dir / "projects" / encoded / "memory"
    memory.mkdir(parents=True)
    (memory / "claude-md.proposal.md").write_text(
        "<!-- claude-md proposals (append-only). Review and merge into CLAUDE.md or discard. -->\n"
        "\n"
        "## 2026-05-20T10:00:00-03:00\n"
        "\n"
        "- **Rule:** Verify changelog before reading subagent claims\n"
        "  - **Rationale:** Subagent hallucinated worktree.bgIsolation as boolean\n"
    )

    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "context_inject.py"
    )

    import os

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(claude_dir),
    }
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
        env=env,
    )
    assert result.returncode == 0
    ctx = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "## Proposals to review" in ctx
    assert "Verify changelog before reading subagent claims" in ctx


def test_proposals_summary_line_counts_entries_and_oldest_date(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "claude-md.proposal.md").write_text(
        "<!-- claude-md proposals (append-only). Review and merge into CLAUDE.md or discard. -->\n"
        "\n"
        "## 2026-05-20T10:00:00-03:00\n"
        "\n"
        "- **Rule:** Always use os.replace for iCloud-synced paths\n"
        "\n"
        "## 2026-05-18T09:00:00-03:00\n"
        "\n"
        "- **Rule:** Verify changelog before reading subagent claims\n"
    )

    line = proposals_summary_line(memory)

    assert line == (
        "⚠ 2 claude-md proposal(s) pending (oldest 2026-05-18) — review: lh memory proposals"
    )


def test_proposals_summary_line_counts_rules_within_one_section(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "claude-md.proposal.md").write_text(
        "<!-- claude-md proposals (append-only). Review and merge into CLAUDE.md or discard. -->\n"
        "\n"
        "## 2026-05-20T10:00:00-03:00\n"
        "\n"
        "- **Rule:** Always use os.replace for iCloud-synced paths\n"
        "- **Rule:** Verify changelog before reading subagent claims\n"
    )

    line = proposals_summary_line(memory)

    assert line == (
        "⚠ 2 claude-md proposal(s) pending (oldest 2026-05-20) — review: lh memory proposals"
    )


def test_proposals_summary_line_ignores_content_inside_html_comments(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "claude-md.proposal.md").write_text(
        "<!-- archived 2026-01-05\n"
        "## 2026-01-01T08:00:00-03:00\n"
        "\n"
        "- **Rule:** Archived rule that must not count\n"
        "-->\n"
        "\n"
        "## 2026-05-20T10:00:00-03:00\n"
        "\n"
        "- **Rule:** Always use os.replace for iCloud-synced paths\n"
    )

    line = proposals_summary_line(memory)

    assert line == (
        "⚠ 1 claude-md proposal(s) pending (oldest 2026-05-20) — review: lh memory proposals"
    )


def test_proposals_summary_line_empty_when_no_pending_entries(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "claude-md.proposal.md").write_text(
        "<!-- claude-md proposals (append-only). Review and merge into CLAUDE.md or discard. -->\n"
        "\n"
        "Archived notes without any timestamped entry headings.\n"
    )

    assert proposals_summary_line(memory) == ""


def test_proposals_summary_line_empty_when_no_file(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    assert proposals_summary_line(memory) == ""


def test_truncate_body_emits_proposals_summary_when_section_dropped() -> None:
    git = "## Git\nBranch: main"
    proposals = "## Proposals to review\n" + ("p" * 600)
    summary = "⚠ 1 claude-md proposal(s) pending (oldest 2026-05-20) — review: lh memory proposals"

    result = _truncate_body(
        200, git, "", "", "", "", proposals_section=proposals, proposals_summary=summary
    )

    assert "## Proposals to review" not in result
    assert summary in result


def test_truncate_body_omits_summary_when_proposals_section_shown() -> None:
    git = "## Git\nBranch: main"
    proposals = "## Proposals to review\n- a pending rule"
    summary = "⚠ 1 claude-md proposal(s) pending (oldest 2026-05-20) — review: lh memory proposals"

    result = _truncate_body(
        3000, git, "", "", "", "", proposals_section=proposals, proposals_summary=summary
    )

    assert "## Proposals to review" in result
    assert summary not in result


def test_truncate_body_proposals_summary_survives_extreme_truncation() -> None:
    git = "## Git\nBranch: main"
    big_north = "## LazyNorth\n" + ("n" * 500)
    big_handoff = "## Handoff from last session\n" + ("h" * 500)
    big_episodic = "## Recent history\n" + ("e" * 500)
    proposals = "## Proposals to review\n" + ("p" * 500)
    summary = "⚠ 3 claude-md proposal(s) pending (oldest 2026-05-01) — review: lh memory proposals"

    result = _truncate_body(
        50,
        git,
        big_north,
        "",
        big_handoff,
        big_episodic,
        proposals_section=proposals,
        proposals_summary=summary,
    )

    assert "## Proposals to review" not in result
    assert summary in result


def _run_hook_in_process(monkeypatch, capsys, cwd: Path, cfg_file: Path) -> str:
    import io
    import json as _json
    import sys as _sys

    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import context_inject as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(_sys, "stdin", io.StringIO("{}"))
    hook_mod.main()
    payload = _json.loads(capsys.readouterr().out)
    return str(payload["hookSpecificOutput"]["additionalContext"])


def test_context_inject_emits_proposals_summary_under_budget_pressure(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

    cwd = tmp_path / "proj"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "claude-md.proposal.md").write_text(
        "<!-- claude-md proposals (append-only). -->\n"
        "\n"
        "## 2026-05-20T10:00:00-03:00\n"
        "\n"
        "- **Rule:** " + ("x" * 400) + "\n"
        "\n"
        "## 2026-05-18T09:00:00-03:00\n"
        "\n"
        "- **Rule:** " + ("y" * 400) + "\n"
    )

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[harness]\nversion = "1"\n\n[context_inject]\nmax_body_chars = 200\n')

    body = _run_hook_in_process(monkeypatch, capsys, cwd, cfg_file)

    assert "## Proposals to review" not in body
    assert (
        "⚠ 2 claude-md proposal(s) pending (oldest 2026-05-18) — review: lh memory proposals"
    ) in body


def test_context_inject_proposals_summary_knob_false_restores_old_behavior(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

    cwd = tmp_path / "proj"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "claude-md.proposal.md").write_text(
        "<!-- claude-md proposals (append-only). -->\n"
        "\n"
        "## 2026-05-20T10:00:00-03:00\n"
        "\n"
        "- **Rule:** " + ("x" * 400) + "\n"
    )

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[harness]\nversion = "1"\n\n'
        "[context_inject]\nmax_body_chars = 200\nproposals_summary = false\n"
    )

    body = _run_hook_in_process(monkeypatch, capsys, cwd, cfg_file)

    assert "## Proposals to review" not in body
    assert "claude-md proposal(s) pending" not in body


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


def test_context_inject_routes_memory_dir_through_agent_adapter(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """ADR-032 L3/L4: the memory dir must come from the configured agent
    adapter. With agent.type = "null" the handoff must be read from under
    ~/.null even when CLAUDE_CONFIG_DIR points elsewhere."""
    import io
    import json as _json
    import sys as _sys

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "decoy-claude"))

    cwd = tmp_path / "proj"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = home / ".null" / "projects" / encoded / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "handoff.md").write_text("resume the adapter-routing work\n")

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[harness]\nversion = "1"\n\n[agent]\ntype = "null"\n')
    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import context_inject as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(_sys, "stdin", io.StringIO("{}"))
    hook_mod.main()

    payload = _json.loads(capsys.readouterr().out)
    body = payload["hookSpecificOutput"]["additionalContext"]
    assert "resume the adapter-routing work" in body
