"""The Stop hook must hand the persister a machine-local cursor directory.

A `cursor_dir` parameter nothing passes is a fix that ships without running.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys as _sys
from pathlib import Path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_hook_passes_a_cursor_dir_under_the_agent_runtime_dir(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    cwd = tmp_path / "proj"
    cwd.mkdir()
    _git(cwd, "init", "-q")
    _git(cwd, "remote", "add", "origin", "git@github.com:lazynet/proj.git")

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[harness]\nversion = "1"\n\n[agent]\ntype = "null"\n')

    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import engram_persist as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)

    captured: dict[str, Path | None] = {}

    class FakePersister:
        def __init__(
            self,
            *,
            memory_dir: Path,
            logs_dir: Path,
            project_key: str,
            engram_bin: str | None = None,
            cursor_dir: Path | None = None,
        ) -> None:
            captured["memory_dir"] = memory_dir
            captured["cursor_dir"] = cursor_dir

        def persist_new_entries(self) -> None:
            pass

    monkeypatch.setattr("lazy_harness.knowledge.engram_persist.EngramPersister", FakePersister)
    monkeypatch.setattr(_sys, "stdin", io.StringIO(json.dumps({"cwd": str(cwd)})))
    hook_mod.main()

    cursor_dir = captured["cursor_dir"]
    assert cursor_dir is not None
    # Machine-local: under the agent runtime dir, never under the memory dir.
    assert home / ".null" in cursor_dir.parents
    memory_dir = captured["memory_dir"]
    assert memory_dir is not None
    assert memory_dir not in cursor_dir.parents
    assert cursor_dir != memory_dir


def test_two_repos_of_the_same_name_get_different_cursor_dirs(tmp_path: Path, monkeypatch) -> None:
    """The key must carry the remote, not just the directory basename."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[harness]\nversion = "1"\n\n[agent]\ntype = "null"\n')

    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import engram_persist as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)

    seen: list[Path] = []

    class FakePersister:
        def __init__(self, *, cursor_dir: Path | None = None, **_: object) -> None:
            assert cursor_dir is not None
            seen.append(cursor_dir)

        def persist_new_entries(self) -> None:
            pass

    monkeypatch.setattr("lazy_harness.knowledge.engram_persist.EngramPersister", FakePersister)

    for owner in ("lazynet", "someone-else"):
        cwd = tmp_path / owner / "proj"
        cwd.mkdir(parents=True)
        _git(cwd, "init", "-q")
        _git(cwd, "remote", "add", "origin", f"git@github.com:{owner}/proj.git")
        monkeypatch.setattr(_sys, "stdin", io.StringIO(json.dumps({"cwd": str(cwd)})))
        hook_mod.main()

    assert len(seen) == 2
    assert seen[0] != seen[1]
