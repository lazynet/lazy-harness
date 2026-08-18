"""One resolver for where a project's distilled memory lives.

Twelve places built this path themselves, each appending `/ "memory"` to a
project directory derived from the absolute cwd. Every reader and writer of a
config-derived path has to resolve it the same way, or one of them ends up
writing a file nothing reads.
"""

from __future__ import annotations

from pathlib import Path


def _store(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "knowledge.toml").write_text(
        '[knowledge]\nversion   = 1\nsessions  = "sessions"\n'
        'learnings = "learnings"\nmemory    = "memory"\n'
    )
    return root


def _repo(tmp_path: Path, remote: str) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {remote}\n')
    return root


def test_memory_lives_in_the_knowledge_store_under_the_project_key(tmp_path: Path) -> None:
    from lazy_harness.core.memory_store import memory_dir_for

    store = _store(tmp_path)
    repo = _repo(tmp_path, "git@github.com:lazynet/x.git")

    assert memory_dir_for(repo, knowledge_root=store) == store / "memory" / "github.com/lazynet/x"


def test_the_same_repository_resolves_identically_from_two_paths(tmp_path: Path) -> None:
    """The whole point: two checkouts of one repository at different absolute
    paths must land on one directory."""
    from lazy_harness.core.memory_store import memory_dir_for

    store = _store(tmp_path)
    mac = tmp_path / "Users" / "me" / "x"
    linux = tmp_path / "home" / "me" / "x"
    for root in (mac, linux):
        (root / ".git").mkdir(parents=True)
        (root / ".git" / "config").write_text('[remote "origin"]\n\turl = git@github.com:o/x.git\n')

    assert memory_dir_for(mac, knowledge_root=store) == memory_dir_for(linux, knowledge_root=store)


def test_a_declared_memory_area_is_used(tmp_path: Path) -> None:
    from lazy_harness.core.memory_store import memory_dir_for

    store = tmp_path / "knowledge"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion   = 1\nsessions  = "sessions"\n'
        'learnings = "learnings"\nmemory    = "distilled"\n'
    )
    repo = _repo(tmp_path, "git@github.com:o/x.git")

    assert memory_dir_for(repo, knowledge_root=store) == store / "distilled" / "github.com/o/x"


def test_without_a_knowledge_store_it_falls_back_to_the_legacy_location(tmp_path: Path) -> None:
    """A machine with no knowledge store keeps working exactly as before,
    unshared. Degrading to the old path is the difference between "not synced
    yet" and "memory disappeared"."""
    from lazy_harness.core.memory_store import memory_dir_for

    repo = _repo(tmp_path, "git@github.com:o/x.git")
    legacy = tmp_path / "profile"

    resolved = memory_dir_for(repo, knowledge_root=None, legacy_project_dir=legacy)

    assert resolved == legacy / "memory"


def test_an_unreadable_marker_falls_back_rather_than_raising(tmp_path: Path) -> None:
    """This runs inside hooks. A malformed marker must not take the session
    down with it."""
    from lazy_harness.core.memory_store import memory_dir_for

    store = tmp_path / "knowledge"
    store.mkdir()
    (store / "knowledge.toml").write_text("this is not toml [[[")
    repo = _repo(tmp_path, "git@github.com:o/x.git")
    legacy = tmp_path / "profile"

    assert memory_dir_for(repo, knowledge_root=store, legacy_project_dir=legacy) == (
        legacy / "memory"
    )


def test_the_resolved_path_never_escapes_the_memory_area(tmp_path: Path) -> None:
    from lazy_harness.core.memory_store import memory_dir_for

    store = _store(tmp_path)
    repo = _repo(tmp_path, "https://example.org/../../etc/passwd")

    resolved = memory_dir_for(repo, knowledge_root=store)

    assert (store / "memory") in resolved.parents or resolved.parent == store / "memory"
