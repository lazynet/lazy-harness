"""Which legacy memory is still worth something, and which is a leftover.

`plan_migration` answers "where would this go". It does not answer the question
a person actually asks — is there curated memory sitting somewhere nothing
reads any more? A directory whose target already exists in the store is a
harmless leftover. One whose target does not is memory that was written and
then lost sight of.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.memory_migration import classify_legacy_memory


def _legacy(profile: Path, encoded: str, *, memory: str = "# notes\n") -> Path:
    d = profile / "projects" / encoded / "memory"
    d.mkdir(parents=True)
    (d / "MEMORY.md").write_text(memory)
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
        "[knowledge]\n"
        "version   = 1\n"
        'sessions  = "sessions"\n'
        'learnings = "learnings"\n'
        'memory    = "memory"\n'
    )
    return root


def _encoded_for(repo: Path) -> str:
    return "-" + str(repo).lstrip("/").replace("/", "-")


def test_memory_absent_from_the_store_is_reported_as_orphaned(tmp_path: Path) -> None:
    store = _store(tmp_path)
    profile = tmp_path / "profile"
    repo = _repo(tmp_path, "proj", "git@github.com:o/proj.git")
    _legacy(profile, _encoded_for(repo))

    statuses = classify_legacy_memory([profile], knowledge_root=store)

    assert len(statuses) == 1
    assert statuses[0].status == "orphaned"
    assert statuses[0].checkout == repo


def test_memory_already_in_the_store_is_reported_as_superseded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    profile = tmp_path / "profile"
    repo = _repo(tmp_path, "proj", "git@github.com:o/proj.git")
    _legacy(profile, _encoded_for(repo))
    target = store / "memory" / "github.com" / "o" / "proj"
    target.mkdir(parents=True)
    (target / "MEMORY.md").write_text("# the copy that is actually read\n")

    statuses = classify_legacy_memory([profile], knowledge_root=store)

    assert [s.status for s in statuses] == ["superseded"]


def test_memory_whose_checkout_is_gone_is_reported_as_unkeyable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    profile = tmp_path / "profile"
    _legacy(profile, "-gone-forever-repo")

    statuses = classify_legacy_memory([profile], knowledge_root=store)

    assert [s.status for s in statuses] == ["unkeyable"]
    assert statuses[0].checkout is None
    assert statuses[0].detail


def test_a_repo_without_a_remote_is_unkeyable_not_orphaned(tmp_path: Path) -> None:
    """Nothing to key on, so nowhere to move it — but it is not lost either."""
    store = _store(tmp_path)
    profile = tmp_path / "profile"
    repo = tmp_path / "noremote"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_text("[core]\n\tbare = false\n")
    _legacy(profile, _encoded_for(repo))

    statuses = classify_legacy_memory([profile], knowledge_root=store)

    assert [s.status for s in statuses] == ["unkeyable"]


def test_classification_touches_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    profile = tmp_path / "profile"
    repo = _repo(tmp_path, "proj", "git@github.com:o/proj.git")
    legacy = _legacy(profile, _encoded_for(repo))

    classify_legacy_memory([profile], knowledge_root=store)

    assert (legacy / "MEMORY.md").is_file()
    assert not (store / "memory").exists()
