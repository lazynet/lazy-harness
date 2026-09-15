"""Tests for shared builtin-hook helpers."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


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


def test_declared_transcript_reads_snake_case_key(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import _declared_transcript

    transcript = tmp_path / "abc123.jsonl"
    transcript.write_text("{}\n")

    assert _declared_transcript({"transcript_path": str(transcript)}) == transcript


def test_declared_transcript_reads_camel_case_key(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import _declared_transcript

    transcript = tmp_path / "abc123.jsonl"
    transcript.write_text("{}\n")

    assert _declared_transcript({"transcriptPath": str(transcript)}) == transcript


def test_declared_transcript_returns_none_when_key_absent() -> None:
    from lazy_harness.hooks.builtins._shared import _declared_transcript

    assert _declared_transcript({"session_id": "abc123"}) is None


def test_declared_transcript_does_not_touch_the_filesystem(tmp_path: Path) -> None:
    """The declaration is what the payload said, not what exists.

    `existing_transcript` owns the `.is_file()` half; keeping them apart is what
    lets `resolve_project_dir` work at SessionStart, before the file is written.
    """
    from lazy_harness.hooks.builtins._shared import _declared_transcript

    missing = tmp_path / "nowhere" / "gone.jsonl"

    assert _declared_transcript({"transcript_path": str(missing)}) == missing


def test_declared_transcript_returns_none_for_non_mapping() -> None:
    from lazy_harness.hooks.builtins._shared import _declared_transcript

    assert _declared_transcript(None) is None
    assert _declared_transcript("transcript_path") is None


def test_existing_transcript_filters_a_declared_path_that_is_not_written_yet(
    tmp_path: Path,
) -> None:
    """SessionStart declares a transcript before the agent writes it.

    `HookEvent.transcript_path` is the declared path, un-stat'd, so the filter
    the deleted `transcript_from_payload` applied has to survive somewhere --
    here. Without a house of its own it vanishes at every call site at once.
    """
    from lazy_harness.hooks.builtins._shared import existing_transcript

    assert existing_transcript(tmp_path / "absent.jsonl") is None
    written = tmp_path / "present.jsonl"
    written.write_text("{}\n")
    assert existing_transcript(written) == written
    assert existing_transcript(None) is None


def test_existing_transcript_rejects_a_directory(tmp_path: Path) -> None:
    """`.is_file()`, not `.exists()` — the project dir shares the path shape."""
    from lazy_harness.hooks.builtins._shared import existing_transcript

    assert existing_transcript(tmp_path) is None


def test_resolve_project_dir_prefers_the_declared_dir(tmp_path: Path) -> None:
    """The agent owns the project-dir naming; we read it, never recompute it."""
    from lazy_harness.hooks.builtins._shared import resolve_project_dir

    agent_dir = tmp_path / "agent"
    declared = agent_dir / "projects" / "-encoded-by-the-agent"
    declared.mkdir(parents=True)

    resolved = resolve_project_dir(
        declared / "s.jsonl",
        agent_dir=agent_dir,
        sessions_subdir="projects",
        cwd=Path("/Users/x/some where/proj"),
    )

    assert resolved == declared


def test_resolve_project_dir_honours_a_transcript_not_written_yet(tmp_path: Path) -> None:
    """At SessionStart the transcript file does not exist, but its dir does.

    Only the parent is stat'd, which is why this helper takes the declared path
    and not the `existing_transcript` of it.
    """
    from lazy_harness.hooks.builtins._shared import resolve_project_dir

    agent_dir = tmp_path / "agent"
    declared = agent_dir / "projects" / "-encoded-by-the-agent"
    declared.mkdir(parents=True)
    unwritten = declared / "0197f0de-cafe-4bad-9001-000000000003.jsonl"

    resolved = resolve_project_dir(
        unwritten,
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
        stray / "transcript.jsonl",
        agent_dir=agent_dir,
        sessions_subdir="projects",
        cwd=Path("/Users/x/proj"),
    )

    assert resolved == agent_dir / "projects" / "-Users-x-proj"


def test_resolve_project_dir_ignores_a_declared_dir_that_is_gone(tmp_path: Path) -> None:
    """A stale transcript path from a deleted project dir derives from cwd instead."""
    from lazy_harness.hooks.builtins._shared import resolve_project_dir

    agent_dir = tmp_path / "agent"
    stale = agent_dir / "projects" / "-removed-by-the-agent" / "abc.jsonl"

    resolved = resolve_project_dir(
        stale,
        agent_dir=agent_dir,
        sessions_subdir="projects",
        cwd=Path("/Users/x/proj"),
    )

    assert resolved == agent_dir / "projects" / "-Users-x-proj"


def test_resolve_project_dir_falls_back_to_cwd_encoding(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import resolve_project_dir

    agent_dir = tmp_path / "agent"

    resolved = resolve_project_dir(
        None,
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
        declared / "s.jsonl",
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
        None, agent_dir=agent_dir, sessions_subdir="projects", cwd=plain
    ) == resolve_project_dir(None, agent_dir=agent_dir, sessions_subdir="projects", cwd=plain)


def test_project_key_is_identical_from_every_entry_point(tmp_path: Path) -> None:
    """One repo, one key — whichever directory the agent was launched from.

    Asserting each entry point against its own expected value hides the bug
    this catches: the worktree path resolves symlinks (git hands back an
    absolute gitdir) while the parent walk does not, so on macOS the same
    repo yielded /var/... and /private/var/... — two keys, one repo.
    """
    from lazy_harness.hooks.builtins._shared import project_key

    real = tmp_path / "real"
    real.mkdir()
    repo, worktree = _init_repo_with_worktree(real)
    artifacts = repo / "graphify-out"
    artifacts.mkdir()

    # Reach the same repo through a symlink, the way /var -> /private/var does
    # on macOS. Only the worktree branch resolves it, so the keys diverge.
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    linked_repo = link / repo.name

    assert project_key(linked_repo / "graphify-out") == project_key(
        linked_repo / ".worktrees" / "feat"
    ), "the same repo produced two keys depending on the entry point"
    assert project_key(artifacts) == project_key(worktree) == project_key(repo)


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


def test_the_two_project_key_resolvers_agree_on_the_repo_root_for_a_worktree(
    tmp_path: Path,
) -> None:
    """`core.project_identity.project_key` (remote-keyed) and this module's
    `project_key` (path-keyed) answer the identity question two different
    ways, but both must collapse a worktree cwd onto the same main checkout —
    `lh memory rightsize` (ADR-030 G7) picks the former deliberately, and this
    is what would silently fragment a scanned project into two rows if a
    future edit made the two resolvers disagree about the root."""
    from lazy_harness.core.project_identity import main_repo_root
    from lazy_harness.core.project_identity import project_key as identity_project_key
    from lazy_harness.hooks.builtins._shared import project_key as shared_project_key

    repo, worktree = _init_repo_with_worktree(tmp_path)
    (repo / ".git" / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/o/myrepo.git\n'
    )

    assert identity_project_key(worktree) == "github.com/o/myrepo"
    assert Path(shared_project_key(worktree)) == main_repo_root(worktree).resolve()


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


# --- transcript_reader ------------------------------------------------------
#
# Decision 11 of `specs/designs/2026-09-13-multi-agent-harness-design.md` makes
# transcript dependence a declared capability. A builtin that needs a signal has
# to ask *someone* for it, and this is the one place that answers — resolved
# per profile, because `[profiles.<name>].agent` is what decides whose wire
# format the session is speaking.


def _profile_config(tmp_path: Path, agent: str) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "lazy"\n\n'
        f'[profiles.lazy]\nconfig_dir = "{tmp_path / "cc"}"\nagent = "{agent}"\n'
    )
    return cfg


def test_transcript_reader_resolves_the_adapter_of_the_profiles_own_agent(
    tmp_path: Path, monkeypatch
) -> None:
    from lazy_harness.agents.base import TranscriptReader
    from lazy_harness.hooks.builtins._shared import transcript_reader

    monkeypatch.setattr(
        "lazy_harness.core.paths.config_file", lambda: _profile_config(tmp_path, "claude-code")
    )

    assert isinstance(transcript_reader("lazy"), TranscriptReader)


def test_transcript_reader_is_none_when_the_profiles_agent_cannot_be_read(
    tmp_path: Path, monkeypatch
) -> None:
    """The case decision 11 exists for: a hook must learn the signal is absent.

    Returning a reader that yields nothing would be indistinguishable from a
    session that declared no goal, which is the silent pass the decision names.
    """
    from lazy_harness.hooks.builtins._shared import transcript_reader

    monkeypatch.setattr(
        "lazy_harness.core.paths.config_file", lambda: _profile_config(tmp_path, "null")
    )

    assert transcript_reader("lazy") is None


def test_transcript_reader_falls_back_to_the_global_agent_without_a_config(
    tmp_path: Path, monkeypatch
) -> None:
    """No config is a machine that has not run `lh init`, not an agent change.

    The runner resolves an absent config the same way, for the same reason:
    refusing there would take every hook down with it.
    """
    from lazy_harness.agents.base import TranscriptReader
    from lazy_harness.hooks.builtins._shared import transcript_reader

    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: tmp_path / "absent.toml")

    assert isinstance(transcript_reader(""), TranscriptReader)


def test_transcript_reader_is_none_for_an_unregistered_agent(tmp_path: Path, monkeypatch) -> None:
    """A typo in `[profiles.<name>].agent` leaves the hook without a signal."""
    from lazy_harness.hooks.builtins._shared import transcript_reader

    monkeypatch.setattr(
        "lazy_harness.core.paths.config_file", lambda: _profile_config(tmp_path, "codex")
    )

    assert transcript_reader("lazy") is None


def test_transcript_reader_rejects_an_adapter_that_only_half_implements_it(
    tmp_path: Path, monkeypatch
) -> None:
    """A reader missing one Protocol method is refused, not called and crashed.

    `_goal_declared` calls `read()` on whatever comes back, so an adapter that
    grew `signals()` and not `read()` would raise `AttributeError` inside the
    guard. The `isinstance` check against a `runtime_checkable` Protocol is
    what makes that a `None` instead.
    """
    from lazy_harness.hooks.builtins._shared import transcript_reader

    class _HalfReader:
        """Declares signals, cannot read — the shape a half-done port has."""

        def signals(self):
            return set()

    monkeypatch.setattr(
        "lazy_harness.core.paths.config_file", lambda: _profile_config(tmp_path, "half")
    )
    monkeypatch.setitem(
        __import__("lazy_harness.agents.registry", fromlist=["_AGENTS"])._AGENTS,
        "half",
        _HalfReader,
    )

    assert transcript_reader("lazy") is None


def test_transcript_reader_uses_an_injected_config_instead_of_the_file_on_disk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`lh doctor` has already loaded a config; a second read could disagree."""
    from lazy_harness.agents.base import Signal
    from lazy_harness.core.config import Config, ProfileEntry
    from lazy_harness.core.paths import config_file as real_config_file
    from lazy_harness.hooks.builtins._shared import transcript_reader

    def _refuse() -> object:
        raise AssertionError("transcript_reader re-read config.toml despite an injected cfg")

    monkeypatch.setattr("lazy_harness.core.paths.config_file", _refuse)
    assert real_config_file is not None

    cfg = Config()
    cfg.agent.type = "null"
    cfg.profiles.items = {"p1": ProfileEntry(config_dir="~/.agent-p1", agent="claude-code")}

    reader = transcript_reader("p1", cfg)

    assert reader is not None
    assert Signal.GOAL_STATUS in reader.signals()


# --- agent_dir_for ----------------------------------------------------------
#
# The one importable answer to "which agent does this profile run, and which
# directory do its hooks write under". Six builtins asked `cfg.agent.type` and
# `agent_runtime_dir(agent)` separately, which is two global answers to a
# per-profile question.


def _two_agent_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "daily"\n\n'
        f'[profiles.daily]\nconfig_dir = "{tmp_path / "claude-daily"}"\n\n'
        f'[profiles.gate]\nconfig_dir = "{tmp_path / "codex-home"}"\nagent = "codex"\n'
    )
    return cfg


def test_agent_dir_for_returns_the_profiles_own_agent_and_config_dir(tmp_path: Path) -> None:
    """The step 4 gate's F4: a hook invoked with `--profile gate-throwaway` wrote
    its log into the user's real `~/.codex`, because neither half of this answer
    was resolved per profile."""
    from lazy_harness.core.config import load_config
    from lazy_harness.hooks.builtins._shared import agent_dir_for

    cfg = load_config(_two_agent_config(tmp_path))

    agent, agent_dir = agent_dir_for(cfg, "gate")

    assert agent.name == "codex"
    assert agent_dir == tmp_path / "codex-home"


def test_agent_dir_for_a_profile_inheriting_the_global_agent(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config
    from lazy_harness.hooks.builtins._shared import agent_dir_for

    cfg = load_config(_two_agent_config(tmp_path))

    agent, agent_dir = agent_dir_for(cfg, "daily")

    assert agent.name == "claude-code"
    assert agent_dir == tmp_path / "claude-daily"


def test_agent_dir_for_without_a_config_falls_back_to_claude_code(home_dir: Path) -> None:
    """A machine that has not run `lh init` still has an agent whose dirs its
    hooks write under — the same degradation `transcript_reader` applies."""
    from lazy_harness.hooks.builtins._shared import agent_dir_for

    agent, agent_dir = agent_dir_for(None, "")

    assert agent.name == "claude-code"
    assert agent_dir == home_dir / ".claude"
