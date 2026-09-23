"""Static checks for the single-file repository instruction contract."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.repo_instructions import check_repository

AGENTS_BODY = "# AGENTS.md — fixture\n\nEvery change goes through the gate.\n"


def _codes(root: Path) -> list[tuple[str, str]]:
    return [(finding.path.as_posix(), finding.code) for finding in check_repository(root)]


def test_a_repository_with_only_root_agents_md_is_clean(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(AGENTS_BODY)

    assert check_repository(tmp_path) == []


def test_a_missing_root_agents_md_is_reported(tmp_path: Path) -> None:
    assert _codes(tmp_path) == [("AGENTS.md", "missing-agents-md")]


def test_root_claude_md_is_rejected_because_it_shadows_parent_agents(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(AGENTS_BODY)
    (tmp_path / "CLAUDE.md").write_text("# Claude-only rules\n")

    assert _codes(tmp_path) == [("CLAUDE.md", "claude-md-shadows-agents")]


def test_nested_claude_md_is_rejected_even_with_a_sibling_agents(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(AGENTS_BODY)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "AGENTS.md").write_text("# Nested rules\n")
    (nested / "CLAUDE.md").write_text("# Nested Claude rules\n")

    assert _codes(tmp_path) == [("nested/CLAUDE.md", "claude-md-shadows-agents")]


def test_nested_claude_md_without_a_sibling_agents_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(AGENTS_BODY)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "CLAUDE.md").write_text("# Claude-only rules\n")

    assert _codes(tmp_path) == [("nested/CLAUDE.md", "claude-md-shadows-agents")]


def test_claude_md_inside_the_project_claude_directory_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(AGENTS_BODY)
    nested = tmp_path / ".claude"
    nested.mkdir()
    (nested / "CLAUDE.md").write_text("# Hidden Claude rules\n")

    assert _codes(tmp_path) == [(".claude/CLAUDE.md", "claude-md-shadows-agents")]


def test_foreign_checkout_and_vendored_directories_are_not_walked(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(AGENTS_BODY)
    hidden = tmp_path / ".worktrees" / "wip"
    hidden.mkdir(parents=True)
    (hidden / "CLAUDE.md").write_text("# Ignored checkout\n")
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "CLAUDE.md").write_text("# Ignored dependency\n")

    assert check_repository(tmp_path) == []


def test_a_nested_git_checkout_is_not_walked_wherever_it_lives(tmp_path: Path) -> None:
    # Claude Code creates its own worktrees under `.claude/worktrees/`, a path
    # no skip-list names; each carries a `.git` file and another branch's files.
    (tmp_path / "AGENTS.md").write_text(AGENTS_BODY)
    worktree = tmp_path / ".claude" / "worktrees" / "feature"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/feature\n")
    (worktree / "CLAUDE.md").write_text("# Another branch's rules\n")

    assert check_repository(tmp_path) == []


def test_an_ancestor_dot_claude_claude_md_is_reported(tmp_path: Path) -> None:
    # Measured on Claude Code 2.1.280: any ancestor `.claude/CLAUDE.md` (e.g. a
    # `~/.claude` link to a profile) stops the repository AGENTS.md loading.
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "CLAUDE.md").write_text("# Global doc\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(AGENTS_BODY)

    findings = check_repository(repo)

    assert [(f.path, f.code) for f in findings] == [
        (tmp_path / ".claude" / "CLAUDE.md", "ancestor-claude-md-shadows-agents")
    ]


def test_an_ancestor_claude_md_is_reported(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# Workspace rules\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(AGENTS_BODY)

    assert [f.code for f in check_repository(repo)] == ["ancestor-claude-md-shadows-agents"]
