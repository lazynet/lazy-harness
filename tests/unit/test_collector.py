"""Tests for session JSONL collector."""

from __future__ import annotations

import json
from pathlib import Path


def _write_session_jsonl(path: Path, messages: list[dict]) -> None:
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def test_parse_session_extracts_tokens(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    session_file = tmp_path / "abc12345.jsonl"
    _write_session_jsonl(
        session_file,
        [
            {"type": "user", "content": "hello", "timestamp": "2026-04-12T10:00:00"},
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_input_tokens": 200,
                        "cache_creation_input_tokens": 10,
                    },
                },
                "timestamp": "2026-04-12T10:00:01",
            },
        ],
    )

    results = parse_session(session_file)
    assert len(results) == 1
    r = results[0]
    assert r["model"] == "claude-opus-4-6"
    assert r["input"] == 100
    assert r["output"] == 50
    assert r["cache_read"] == 200
    assert r["cache_create"] == 10
    assert r["session"] == "abc12345"
    assert r["date"] == "2026-04-12"


def test_parse_session_multiple_models(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    session_file = tmp_path / "def67890.jsonl"
    _write_session_jsonl(
        session_file,
        [
            {"type": "user", "content": "hello", "timestamp": "2026-04-12T10:00:00"},
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            },
            {
                "type": "assistant",
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {"input_tokens": 200, "output_tokens": 100},
                },
            },
        ],
    )

    results = parse_session(session_file)
    assert len(results) == 2
    models = {r["model"] for r in results}
    assert models == {"claude-opus-4-6", "claude-sonnet-4-6"}


def test_parse_session_empty_file(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    session_file = tmp_path / "empty.jsonl"
    session_file.write_text("")
    results = parse_session(session_file)
    assert results == []


def test_extract_project_name() -> None:
    from lazy_harness.monitoring.collector import extract_project_name

    assert extract_project_name("-Users-foo-repos-my-project") == "my-project"


def test_parse_session_uses_full_uuid_as_session_id(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    uuid = "66056f9a-9981-4554-9ada-06237c999d23"
    session_file = tmp_path / f"{uuid}.jsonl"
    _write_session_jsonl(
        session_file,
        [
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-6",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
                "timestamp": "2026-04-13T10:00:00",
            },
        ],
    )

    results = parse_session(session_file)
    assert results[0]["session"] == uuid


def _encode(path: Path) -> str:
    """The project-directory name Claude Code writes for `path`.

    Both `/` and `.` become `-`, which is why a worktree under `.worktrees/`
    cannot be told apart from a directory literally named `worktrees` by
    reading the encoded string alone.
    """
    import re

    return re.sub(r"[/.]", "-", str(path))


def _linked_worktree(tmp_path: Path, repo_name: str, worktree_dir: str, name: str) -> Path:
    """A main checkout plus one linked worktree, on disk, without invoking git.

    Mirrors the shape `core.project_identity.main_repo_root` reads: the
    worktree's `.git` is a file naming `<repo>/.git/worktrees/<name>`.
    """
    root = tmp_path / repo_name
    (root / ".git" / "worktrees" / name).mkdir(parents=True)
    wt = root / worktree_dir / name
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {root}/.git/worktrees/{name}\n")
    return wt


def test_extract_project_name_folds_a_worktree_into_its_main_repo(tmp_path: Path) -> None:
    """Every worktree currently becomes its own project, so a repo worked on
    through worktrees is split across as many rows as it has branches and its
    cost is understated in every one of them."""
    from lazy_harness.monitoring.collector import extract_project_name

    wt = _linked_worktree(tmp_path, "backstage-poc", ".worktree", "aptio-groupby")

    assert extract_project_name(_encode(wt)) == "backstage-poc"


def test_extract_project_name_restores_a_leading_dot(tmp_path: Path) -> None:
    """The encoding maps `.` to `-`, so a path under any dotted directory
    never resolves and silently takes the container fallback."""
    from lazy_harness.monitoring.collector import extract_project_name

    # The name has to carry a dash of its own: with a single-word name the
    # `parts[-1]` fallback returns the right answer for the wrong reason and
    # the test passes whether or not the dot is ever restored.
    target = tmp_path / ".config" / "my-notes"
    target.mkdir(parents=True)

    assert extract_project_name(_encode(target)) == "my-notes"


def test_extract_project_name_keeps_an_ordinary_checkout_name(tmp_path: Path) -> None:
    """The main checkout of a repo must keep answering with its own name."""
    from lazy_harness.monitoring.collector import extract_project_name

    root = tmp_path / "lazy-harness"
    (root / ".git").mkdir(parents=True)

    assert extract_project_name(_encode(root)) == "lazy-harness"
