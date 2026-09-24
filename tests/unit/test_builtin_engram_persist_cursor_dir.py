"""The Stop hook must hand the persister a machine-local cursor directory.

A `cursor_dir` parameter nothing passes is a fix that ships without running.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.unit.test_builtin_engram_persist import _stop_event


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_hook_passes_a_cursor_dir_under_the_agent_runtime_dir(
    tmp_path: Path, monkeypatch, declared_null_sessions: None
) -> None:
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
            adopt_cursor_dirs: tuple[Path, ...] = (),
        ) -> None:
            captured["memory_dir"] = memory_dir
            captured["cursor_dir"] = cursor_dir

        def persist_new_entries(self) -> None:
            pass

    monkeypatch.setattr("lazy_harness.knowledge.engram_persist.EngramPersister", FakePersister)
    hook_mod.main(_stop_event(cwd))

    cursor_dir = captured["cursor_dir"]
    assert cursor_dir is not None
    # Machine-local: under the agent runtime dir, never under the memory dir.
    assert home / ".null" in cursor_dir.parents
    memory_dir = captured["memory_dir"]
    assert memory_dir is not None
    assert memory_dir not in cursor_dir.parents
    assert cursor_dir != memory_dir


def test_two_repos_of_the_same_name_get_different_cursor_dirs(
    tmp_path: Path, monkeypatch, declared_null_sessions: None
) -> None:
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
        hook_mod.main(_stop_event(cwd))

    assert len(seen) == 2
    assert seen[0] != seen[1]


def _two_profile_setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    """A knowledge store plus two profiles, as on a machine running both."""
    from lazy_harness.knowledge.marker import write_marker

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    data = tmp_path / "lh-data"
    monkeypatch.setenv("LH_DATA_DIR", str(data))
    store = tmp_path / "store"
    write_marker(store)
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))

    cwd = tmp_path / "proj"
    cwd.mkdir()
    _git(cwd, "init", "-q")
    _git(cwd, "remote", "add", "origin", "git@github.com:lazynet/proj.git")

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "null"\n\n'
        '[profiles]\ndefault = "alpha"\n\n'
        f'[profiles.alpha]\nconfig_dir = "{home / ".null-alpha"}"\n\n'
        f'[profiles.beta]\nconfig_dir = "{home / ".null-beta"}"\n'
    )
    from lazy_harness.core import paths as paths_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)
    return cwd, store, data


def _capture(monkeypatch) -> list[dict[str, object]]:
    seen: list[dict[str, object]] = []

    class FakePersister:
        def __init__(self, **kwargs: object) -> None:
            seen.append(kwargs)

        def persist_new_entries(self) -> None:
            pass

    monkeypatch.setattr("lazy_harness.knowledge.engram_persist.EngramPersister", FakePersister)
    return seen


def test_profiles_sharing_a_store_share_one_machine_local_cursor(
    tmp_path: Path, monkeypatch, declared_null_sessions: None
) -> None:
    from lazy_harness.hooks.builtins import engram_persist as hook_mod

    cwd, store, data = _two_profile_setup(tmp_path, monkeypatch)
    seen = _capture(monkeypatch)

    hook_mod.main(_stop_event(cwd, profile="alpha"))
    hook_mod.main(_stop_event(cwd, profile="beta"))

    assert len(seen) == 2
    alpha, beta = (Path(str(s["cursor_dir"])) for s in seen)
    assert alpha == beta
    # Machine-local: under the harness data dir, never in the synced store.
    assert data in alpha.parents
    assert store not in alpha.parents
    # Keyed by the memory it indexes.
    memory_dir = Path(str(seen[0]["memory_dir"]))
    assert alpha.parts[-3:] == memory_dir.parts[-3:] == ("github.com", "lazynet", "proj")


def test_the_shared_cursor_adopts_every_profiles_old_cursor(
    tmp_path: Path, monkeypatch, declared_null_sessions: None
) -> None:
    from lazy_harness.hooks.builtins import engram_persist as hook_mod

    cwd, _, _ = _two_profile_setup(tmp_path, monkeypatch)
    seen = _capture(monkeypatch)

    hook_mod.main(_stop_event(cwd, profile="alpha"))

    home = tmp_path / "home"
    adopt = {Path(str(p)) for p in seen[0]["adopt_cursor_dirs"]}  # type: ignore[union-attr]
    suffix = Path("engram-cursors") / "github.com" / "lazynet" / "proj"
    assert adopt == {home / ".null-alpha" / suffix, home / ".null-beta" / suffix}


def test_without_a_store_the_cursor_stays_per_profile(
    tmp_path: Path, monkeypatch, declared_null_sessions: None
) -> None:
    """Memory outside the store is itself per profile, so its cursor must be too."""
    from lazy_harness.hooks.builtins import engram_persist as hook_mod

    cwd, store, data = _two_profile_setup(tmp_path, monkeypatch)
    (store / "knowledge.toml").unlink()
    seen = _capture(monkeypatch)

    hook_mod.main(_stop_event(cwd, profile="alpha"))

    cursor_dir = Path(str(seen[0]["cursor_dir"]))
    assert tmp_path / "home" / ".null-alpha" in cursor_dir.parents
    assert data not in cursor_dir.parents
    assert not seen[0].get("adopt_cursor_dirs")
