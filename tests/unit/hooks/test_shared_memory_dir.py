"""One helper for the memory directory, used by every hook.

Each hook computed a project dir and appended `/ "memory"` itself. That put
distilled memory inside the agent's own project directory — which is named
after the absolute path of the checkout, so the same repository on two machines
wrote to two places.
"""

from __future__ import annotations

from pathlib import Path


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text('[remote "origin"]\n\turl = git@github.com:o/x.git\n')
    return root


def _store(tmp_path: Path) -> Path:
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "knowledge.toml").write_text(
        '[knowledge]\nversion   = 1\nsessions  = "sessions"\n'
        'learnings = "learnings"\nmemory    = "memory"\n'
    )
    return root


def test_the_helper_resolves_into_the_knowledge_store(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import memory_dir

    store = _store(tmp_path)

    resolved = memory_dir(
        {},
        agent_dir=tmp_path / "agent",
        sessions_subdir="projects",
        cwd=_repo(tmp_path),
        knowledge_root=store,
    )

    assert resolved == store / "memory" / "github.com" / "o" / "x"


def test_without_a_store_it_keeps_writing_where_it_always_did(tmp_path: Path) -> None:
    """A machine with no knowledge store keeps working, unshared. Losing sight
    of memory it already wrote would be worse than not sharing it."""
    from lazy_harness.hooks.builtins._shared import memory_dir

    agent_dir = tmp_path / "agent"
    cwd = _repo(tmp_path)

    resolved = memory_dir(
        {},
        agent_dir=agent_dir,
        sessions_subdir="projects",
        cwd=cwd,
        knowledge_root=None,
    )

    assert resolved.name == "memory"
    assert agent_dir in resolved.parents


def test_a_worktree_and_its_main_checkout_agree(tmp_path: Path) -> None:
    """Distilled memory outlives any one worktree."""
    from lazy_harness.hooks.builtins._shared import memory_dir

    root = _repo(tmp_path)
    store = _store(tmp_path)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {root}/.git/worktrees/wt\n")

    kwargs = {
        "agent_dir": tmp_path / "agent",
        "sessions_subdir": "projects",
        "knowledge_root": store,
    }
    assert memory_dir({}, cwd=wt, **kwargs) == memory_dir({}, cwd=root, **kwargs)


def test_a_broken_store_degrades_instead_of_raising(tmp_path: Path) -> None:
    """This runs on the Stop path. A malformed marker must not take the session
    down with it."""
    from lazy_harness.hooks.builtins._shared import memory_dir

    store = tmp_path / "knowledge"
    store.mkdir()
    (store / "knowledge.toml").write_text("not toml [[[")

    resolved = memory_dir(
        {},
        agent_dir=tmp_path / "agent",
        sessions_subdir="projects",
        cwd=_repo(tmp_path),
        knowledge_root=store,
    )

    assert (tmp_path / "agent") in resolved.parents
