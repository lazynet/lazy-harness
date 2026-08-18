"""Moving already-written memory to its identity-keyed home.

Nothing here merges. Two machines that both wrote a `MEMORY.md` for one project
have two curated files, and picking one silently is how months of notes vanish
without anybody noticing which half.
"""

from __future__ import annotations

from pathlib import Path


def _legacy(profile: Path, encoded: str, *, memory: str = "# notes\n") -> Path:
    d = profile / "projects" / encoded / "memory"
    d.mkdir(parents=True)
    (d / "MEMORY.md").write_text(memory)
    (d / "decisions.jsonl").write_text('{"ts":"t","summary":"s"}\n')
    return d


def _repo(tmp_path: Path, name: str, remote: str) -> Path:
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {remote}\n')
    return root


def _store(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "knowledge.toml").write_text(
        '[knowledge]\nversion   = 1\nsessions  = "sessions"\n'
        'learnings = "learnings"\nmemory    = "memory"\n'
    )
    return root


def test_a_plan_is_produced_without_touching_anything(tmp_path: Path) -> None:
    """Dry by default: this moves data a user curated over months."""
    from lazy_harness.core.memory_migration import plan_migration

    store = _store(tmp_path)
    profile = tmp_path / "profile"
    repo = _repo(tmp_path, "x", "git@github.com:o/x.git")
    legacy = _legacy(profile, f"-{str(repo).lstrip('/').replace('/', '-')}")

    moves = plan_migration([profile], knowledge_root=store)

    assert len(moves) == 1
    assert moves[0].source == legacy
    assert moves[0].target == store / "memory" / "github.com" / "o" / "x"
    assert legacy.is_dir(), "planning must not move anything"


def test_a_legacy_dir_whose_checkout_is_gone_is_reported_not_guessed(tmp_path: Path) -> None:
    """The encoded name is a path that may no longer exist. Without the
    checkout there is no remote to read, so there is no identity to move it to
    — and inventing one would file it under the wrong project."""
    from lazy_harness.core.memory_migration import plan_migration

    store = _store(tmp_path)
    profile = tmp_path / "profile"
    _legacy(profile, "-gone-forever-repo")

    moves = plan_migration([profile], knowledge_root=store)

    assert len(moves) == 1
    assert moves[0].target is None
    assert "checkout" in moves[0].reason.lower()


def test_an_occupied_target_is_a_conflict_and_nothing_is_merged(tmp_path: Path) -> None:
    """Two machines each curated a MEMORY.md. Choosing one silently loses the
    other, and merging two hand-written documents produces a third nobody
    wrote."""
    from lazy_harness.core.memory_migration import apply_migration, plan_migration

    store = _store(tmp_path)
    profile = tmp_path / "profile"
    repo = _repo(tmp_path, "x", "git@github.com:o/x.git")
    _legacy(profile, f"-{str(repo).lstrip('/').replace('/', '-')}", memory="# from this machine\n")

    occupied = store / "memory" / "github.com" / "o" / "x"
    occupied.mkdir(parents=True)
    (occupied / "MEMORY.md").write_text("# from the other machine\n")

    moves = plan_migration([profile], knowledge_root=store)
    result = apply_migration(moves)

    assert result.conflicts, "an occupied target must not be written over"
    assert (occupied / "MEMORY.md").read_text() == "# from the other machine\n"


def test_applying_moves_the_files_and_leaves_nothing_behind(tmp_path: Path) -> None:
    from lazy_harness.core.memory_migration import apply_migration, plan_migration

    store = _store(tmp_path)
    profile = tmp_path / "profile"
    repo = _repo(tmp_path, "x", "git@github.com:o/x.git")
    legacy = _legacy(profile, f"-{str(repo).lstrip('/').replace('/', '-')}")

    result = apply_migration(plan_migration([profile], knowledge_root=store))

    target = store / "memory" / "github.com" / "o" / "x"
    assert (target / "MEMORY.md").read_text() == "# notes\n"
    assert (target / "decisions.jsonl").is_file()
    assert not legacy.exists()
    assert result.moved == 1


def test_a_project_with_no_remote_is_left_where_it_is(tmp_path: Path) -> None:
    """Unshared memory does not belong in a store that gets pushed."""
    from lazy_harness.core.memory_migration import plan_migration

    store = _store(tmp_path)
    profile = tmp_path / "profile"
    # A real repository, just without a remote — the case the reason names.
    plain = tmp_path / "plain"
    (plain / ".git").mkdir(parents=True)
    (plain / ".git" / "config").write_text("[core]\n\trepositoryformatversion = 0\n")
    _legacy(profile, f"-{str(plain).lstrip('/').replace('/', '-')}")

    moves = plan_migration([profile], knowledge_root=store)

    assert moves[0].target is None
    assert "remote" in moves[0].reason.lower()


def test_a_home_that_is_itself_a_repository_does_not_swallow_its_children(
    tmp_path: Path,
) -> None:
    """Measured on the real machine: `~/.git` exists, so a walk that returned
    the first directory containing a `.git` resolved every project under it to
    the home directory — 145 of 185 legacy directories collapsed onto one key,
    and the plan silently had nothing to move."""
    from lazy_harness.core.memory_migration import _checkout_for

    home = tmp_path / "home"
    (home / ".git").mkdir(parents=True)
    repo = home / "repos" / "thing"
    (repo / ".git").mkdir(parents=True)

    encoded = "-" + str(repo).lstrip("/").replace("/", "-")

    assert _checkout_for(encoded) == repo


def test_an_existing_but_empty_target_does_not_nest_the_source_inside_it(
    tmp_path: Path,
) -> None:
    """`shutil.move` puts the source *inside* the destination when that
    destination already exists as a directory — even an empty one.

    Observed on the real migration: one project landed at
    `<key>/memory/` instead of `<key>/`, so every reader looked one level too
    high and found nothing.
    """
    from lazy_harness.core.memory_migration import apply_migration, plan_migration

    store = _store(tmp_path)
    profile = tmp_path / "profile"
    repo = _repo(tmp_path, "x", "git@github.com:o/x.git")
    _legacy(profile, f"-{str(repo).lstrip('/').replace('/', '-')}")

    target = store / "memory" / "github.com" / "o" / "x"
    target.mkdir(parents=True)  # exists, empty

    apply_migration(plan_migration([profile], knowledge_root=store))

    assert (target / "MEMORY.md").is_file()
    assert not (target / "memory").exists(), "the source must not land inside the target"
