"""Tests for shared builtin-hook helpers."""

from __future__ import annotations

import os
import time
from pathlib import Path


def test_make_log_writes_prefixed_line_and_creates_parents(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import make_log

    log_file = tmp_path / "logs" / "hooks.log"
    _log = make_log("session-end")
    _log(log_file, "fired cwd=/tmp/x")

    content = log_file.read_text()
    assert content.endswith(" session-end: fired cwd=/tmp/x\n")
    # Timestamp prefix present (ISO format with seconds).
    ts = content.split(" session-end: ")[0]
    assert "T" in ts


def test_make_log_swallows_oserror(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import make_log

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file in the way")
    _log = make_log("pre-compact")
    # Parent of log_file is a regular file → mkdir/open raise; must not bubble.
    _log(blocker / "hooks.log", "must not raise")


def test_find_latest_session_returns_none_for_missing_dir(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import find_latest_session

    assert find_latest_session(tmp_path / "nope") is None


def test_find_latest_session_returns_none_when_no_jsonl(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import find_latest_session

    (tmp_path / "notes.md").write_text("x")
    assert find_latest_session(tmp_path) is None


def test_find_latest_session_picks_most_recent_jsonl(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import find_latest_session

    old = tmp_path / "old.jsonl"
    new = tmp_path / "new.jsonl"
    old.write_text("{}\n")
    new.write_text("{}\n")
    past = time.time() - 600
    os.utime(old, (past, past))

    assert find_latest_session(tmp_path) == new


def test_transcript_from_payload_reads_snake_case_key(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import transcript_from_payload

    transcript = tmp_path / "abc123.jsonl"
    transcript.write_text("{}\n")

    assert transcript_from_payload({"transcript_path": str(transcript)}) == transcript


def test_transcript_from_payload_reads_camel_case_key(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import transcript_from_payload

    transcript = tmp_path / "abc123.jsonl"
    transcript.write_text("{}\n")

    assert transcript_from_payload({"transcriptPath": str(transcript)}) == transcript


def test_transcript_from_payload_returns_none_when_key_absent() -> None:
    from lazy_harness.hooks.builtins._shared import transcript_from_payload

    assert transcript_from_payload({"session_id": "abc123"}) is None


def test_transcript_from_payload_returns_none_when_file_missing(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import transcript_from_payload

    missing = tmp_path / "gone.jsonl"

    assert transcript_from_payload({"transcript_path": str(missing)}) is None


def test_transcript_from_payload_returns_none_for_non_mapping() -> None:
    from lazy_harness.hooks.builtins._shared import transcript_from_payload

    assert transcript_from_payload(None) is None
    assert transcript_from_payload("transcript_path") is None


def test_project_dir_from_payload_is_the_transcript_parent(tmp_path: Path) -> None:
    """The agent owns the project-dir naming; we read it, never recompute it."""
    from lazy_harness.hooks.builtins._shared import project_dir_from_payload

    # Encoding the agent actually uses for a path with a space and a leading dot.
    project_dir = tmp_path / "-Users-x-Mobile-Documents-iCloud-md-obsidian-LazyMind"
    project_dir.mkdir()
    transcript = project_dir / "abc123.jsonl"
    transcript.write_text("{}\n")

    assert project_dir_from_payload({"transcript_path": str(transcript)}) == project_dir


def test_project_dir_from_payload_returns_none_without_transcript() -> None:
    from lazy_harness.hooks.builtins._shared import project_dir_from_payload

    assert project_dir_from_payload({}) is None


def test_project_dir_from_payload_resolves_before_transcript_is_written(
    tmp_path: Path,
) -> None:
    """At SessionStart the transcript file does not exist yet, but its dir does."""
    from lazy_harness.hooks.builtins import _shared

    project_dir = tmp_path / "-Users-x-repos-thing"
    project_dir.mkdir()
    unwritten = project_dir / "0197f0de-cafe-4bad-9001-000000000003.jsonl"

    assert _shared.project_dir_from_payload({"transcript_path": str(unwritten)}) == project_dir
    # The transcript itself is still unusable — only the directory resolves.
    assert _shared.transcript_from_payload({"transcript_path": str(unwritten)}) is None


def test_project_dir_from_payload_returns_none_when_dir_missing(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import project_dir_from_payload

    stale = tmp_path / "gone" / "abc.jsonl"

    assert project_dir_from_payload({"transcript_path": str(stale)}) is None


def test_resolve_project_dir_prefers_the_payload(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import resolve_project_dir

    agent_dir = tmp_path / "agent"
    declared = agent_dir / "projects" / "-encoded-by-the-agent"
    declared.mkdir(parents=True)

    resolved = resolve_project_dir(
        {"transcript_path": str(declared / "s.jsonl")},
        agent_dir=agent_dir,
        sessions_subdir="projects",
        cwd=Path("/Users/x/some where/proj"),
    )

    assert resolved == declared


def test_resolve_project_dir_ignores_a_transcript_outside_the_sessions_root(
    tmp_path: Path,
) -> None:
    """Artifacts stay under the adapter's sessions root (ADR-032), wherever the transcript is."""
    from lazy_harness.hooks.builtins._shared import resolve_project_dir

    agent_dir = tmp_path / "agent"
    stray = tmp_path / "elsewhere"
    stray.mkdir()

    resolved = resolve_project_dir(
        {"transcript_path": str(stray / "transcript.jsonl")},
        agent_dir=agent_dir,
        sessions_subdir="projects",
        cwd=Path("/Users/x/proj"),
    )

    assert resolved == agent_dir / "projects" / "-Users-x-proj"


def test_resolve_project_dir_falls_back_to_cwd_encoding(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import resolve_project_dir

    agent_dir = tmp_path / "agent"

    resolved = resolve_project_dir(
        {},
        agent_dir=agent_dir,
        sessions_subdir="projects",
        cwd=Path("/Users/x/proj"),
    )

    assert resolved == agent_dir / "projects" / "-Users-x-proj"


def _init_repo_with_worktree(root: Path) -> tuple[Path, Path]:
    """Create a git repo plus a linked worktree; return (repo, worktree)."""
    import subprocess

    repo = root / "myrepo"
    repo.mkdir()
    base = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*base, "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [*base, "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    worktree = repo / ".worktrees" / "feat"
    subprocess.run(
        [*base, "worktree", "add", "-q", str(worktree), "-b", "feat"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo, worktree


def test_resolve_memory_dir_uses_the_main_repo_from_inside_a_worktree(tmp_path: Path) -> None:
    """Distilled memory belongs to the repo, not to a worktree that gets deleted."""
    from lazy_harness.hooks.builtins._shared import resolve_memory_dir

    repo, worktree = _init_repo_with_worktree(tmp_path)
    agent_dir = tmp_path / "agent"
    declared = agent_dir / "projects" / ("-" + str(worktree).replace("/", "-").lstrip("-"))
    declared.mkdir(parents=True)

    resolved = resolve_memory_dir(
        {"transcript_path": str(declared / "s.jsonl")},
        agent_dir=agent_dir,
        sessions_subdir="projects",
        cwd=worktree,
    )

    expected = agent_dir / "projects" / ("-" + str(repo.resolve()).replace("/", "-").lstrip("-"))
    assert resolved == expected


def test_resolve_memory_dir_matches_the_project_dir_outside_a_worktree(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import resolve_memory_dir, resolve_project_dir

    agent_dir = tmp_path / "agent"
    plain = tmp_path / "plain"
    plain.mkdir()

    assert resolve_memory_dir(
        {}, agent_dir=agent_dir, sessions_subdir="projects", cwd=plain
    ) == resolve_project_dir({}, agent_dir=agent_dir, sessions_subdir="projects", cwd=plain)


def test_project_key_collapses_a_subdirectory_onto_the_repo_root(tmp_path: Path) -> None:
    """An artifact subdirectory must not become its own project.

    Running the agent from `<repo>/graphify-out` recorded that path verbatim,
    splitting one repo's events across two keys nothing joins back together.
    """
    from lazy_harness.hooks.builtins._shared import project_key

    repo, _ = _init_repo_with_worktree(tmp_path)
    artifacts = repo / "graphify-out"
    artifacts.mkdir()

    assert project_key(artifacts) == str(repo)


def test_project_key_collapses_a_worktree_onto_the_main_repo(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import project_key

    repo, worktree = _init_repo_with_worktree(tmp_path)

    assert project_key(worktree) == str(repo.resolve())


def test_project_key_returns_the_repo_root_unchanged(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import project_key

    repo, _ = _init_repo_with_worktree(tmp_path)

    assert project_key(repo) == str(repo)


def test_project_key_falls_back_to_cwd_outside_a_repo(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import project_key

    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    assert project_key(plain) == str(plain)


def _write_profiles_config(tmp_path: Path, **profiles: Path) -> Path:
    """Config declaring one `[profiles.<name>]` per keyword argument."""
    entries = "\n".join(
        f'\n[profiles.{name}]\nconfig_dir = "{path}"\nroots = ["~"]\n'
        for name, path in profiles.items()
    )
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        f'[profiles]\ndefault = "{next(iter(profiles), "")}"\n{entries}'
    )
    return cfg


def test_profile_name_identifies_the_profile_the_agent_runs_under(
    tmp_path: Path, monkeypatch
) -> None:
    """Every profile writes to one metrics store; a row must name its own.

    Without this the lazy and flex profiles are indistinguishable once both
    start recording, and no per-profile comparison is possible after the fact.
    """
    from lazy_harness.hooks.builtins import _shared

    lazy_dir = tmp_path / "claude-lazy"
    flex_dir = tmp_path / "claude-flex"
    lazy_dir.mkdir()
    flex_dir.mkdir()
    cfg = _write_profiles_config(tmp_path, lazy=lazy_dir, flex=flex_dir)

    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: cfg)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(flex_dir))

    assert _shared.profile_name() == "flex"


def test_profile_name_is_empty_when_the_env_var_is_unset(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.hooks.builtins import _shared

    lazy_dir = tmp_path / "claude-lazy"
    lazy_dir.mkdir()
    cfg = _write_profiles_config(tmp_path, lazy=lazy_dir)

    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: cfg)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    assert _shared.profile_name() == ""


def test_profile_name_is_empty_when_no_profile_matches(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.hooks.builtins import _shared

    lazy_dir = tmp_path / "claude-lazy"
    lazy_dir.mkdir()
    cfg = _write_profiles_config(tmp_path, lazy=lazy_dir)

    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: cfg)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-unknown"))

    assert _shared.profile_name() == ""


def test_profile_name_is_empty_when_the_config_cannot_be_read(tmp_path: Path, monkeypatch) -> None:
    """A broken config must degrade to an unlabelled row, never raise."""
    from lazy_harness.hooks.builtins import _shared

    def _boom() -> Path:
        raise OSError("config unreadable")

    monkeypatch.setattr("lazy_harness.core.paths.config_file", _boom)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))

    assert _shared.profile_name() == ""
