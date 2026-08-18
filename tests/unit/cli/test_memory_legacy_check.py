"""`lh memory legacy-check` — is there curated memory nothing reads any more?

Replaces `cross-profile-check`, which scanned the location memory was moved
out of and compared profiles for a divergence that can no longer exist: the
knowledge root is global, not per-profile, so two profiles cannot hold
different copies of one project's memory.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.memory_cmd import memory


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    store = tmp_path / "knowledge"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        "[knowledge]\n"
        "version   = 1\n"
        'sessions  = "sessions"\n'
        'learnings = "learnings"\n'
        'memory    = "memory"\n'
    )
    profile = tmp_path / "profile-lazy"
    profile.mkdir()
    (tmp_path / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        "[profiles]\n"
        'default = "lazy"\n\n'
        "[profiles.lazy]\n"
        f'config_dir = "{profile}"\n\n'
        "[knowledge]\n"
        f'root = "{store}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    return store, profile


def _repo(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text(
        f'[remote "origin"]\n\turl = git@github.com:o/{name}.git\n'
    )
    return root


def _legacy(profile: Path, repo: Path) -> Path:
    encoded = "-" + str(repo).lstrip("/").replace("/", "-")
    d = profile / "projects" / encoded / "memory"
    d.mkdir(parents=True)
    (d / "MEMORY.md").write_text("# curated over months\n")
    return d


def test_legacy_check_reports_memory_missing_from_the_store(tmp_path: Path, monkeypatch) -> None:
    _store, profile = _setup(tmp_path, monkeypatch)
    repo = _repo(tmp_path, "liverepo")
    _legacy(profile, repo)

    result = CliRunner().invoke(memory, ["legacy-check"])

    assert result.exit_code == 0, result.output
    assert "orphaned" in result.output.lower()
    assert "liverepo" in result.output


def test_legacy_check_does_not_flag_memory_the_store_already_holds(
    tmp_path: Path, monkeypatch
) -> None:
    store, profile = _setup(tmp_path, monkeypatch)
    repo = _repo(tmp_path, "liverepo")
    _legacy(profile, repo)
    target = store / "memory" / "github.com" / "o" / "liverepo"
    target.mkdir(parents=True)
    (target / "MEMORY.md").write_text("# the copy that is read\n")

    result = CliRunner().invoke(memory, ["legacy-check"])

    assert result.exit_code == 0, result.output
    assert "orphaned" not in result.output.lower()
    assert "superseded" in result.output.lower()


def test_legacy_check_points_at_the_command_that_fixes_it(tmp_path: Path, monkeypatch) -> None:
    _store, profile = _setup(tmp_path, monkeypatch)
    repo = _repo(tmp_path, "liverepo")
    _legacy(profile, repo)

    result = CliRunner().invoke(memory, ["legacy-check"])

    assert "lh memory migrate" in result.output


def test_cross_profile_check_is_gone() -> None:
    """It measured the abandoned location and always read clean."""
    assert "cross-profile-check" not in memory.commands
