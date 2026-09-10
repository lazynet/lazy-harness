"""`lh memory rightsize` — every CLAUDE.md the harness can reach, in one set.

Track 1b of `specs/designs/2026-09-10-harness-improvements-design.md`.
Read-only. Reports profile contracts (`<profile config_dir>/CLAUDE.md`) plus
the CLAUDE.md of every project the memory stack already knows about, with
line count, byte count, and which threshold it breaches.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.memory_cmd import memory


def _setup(tmp_path: Path, monkeypatch, *, roots: list[Path] | None = None) -> tuple[Path, Path]:
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
    roots_line = ""
    if roots:
        joined = ", ".join(f'"{r}"' for r in roots)
        roots_line = f"roots = [{joined}]\n"
    (tmp_path / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        "[profiles]\n"
        'default = "lazy"\n\n'
        "[profiles.lazy]\n"
        f'config_dir = "{profile}"\n'
        f"{roots_line}\n"
        "[knowledge]\n"
        f'root = "{store}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    return store, profile


def _repo(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(
        f'[remote "origin"]\n\turl = git@github.com:o/{name}.git\n'
    )
    return root


def _known_to_store(store: Path, name: str) -> None:
    """Give the repo `name` a memory directory in the store — the fixture that
    makes it 'known to the memory stack'."""
    target = store / "memory" / "github.com" / "o" / name
    target.mkdir(parents=True)
    (target / "decisions.jsonl").write_text('{"ts": "2026-09-01", "summary": "x"}\n')


def test_rightsize_reports_a_profile_contract_over_threshold(tmp_path: Path, monkeypatch) -> None:
    _store, profile = _setup(tmp_path, monkeypatch)
    (profile / "CLAUDE.md").write_text("line\n" * 250)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "profile:lazy" in result.output
    assert "250" in result.output
    assert "1/1 over threshold" in result.output


def test_rightsize_stays_quiet_about_a_profile_contract_under_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    _store, profile = _setup(tmp_path, monkeypatch)
    (profile / "CLAUDE.md").write_text("line\n" * 50)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "0/1 over threshold" in result.output


def test_rightsize_lists_a_project_claude_md_known_to_the_memory_stack(
    tmp_path: Path, monkeypatch
) -> None:
    repos = tmp_path / "repos"
    repos.mkdir()
    store, _profile = _setup(tmp_path, monkeypatch, roots=[repos])
    repo = _repo(repos, "widget")
    (repo / "CLAUDE.md").write_text("line\n" * 300)
    _known_to_store(store, "widget")

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "project:github.com/o/widget" in result.output
    assert "300" in result.output


def test_rightsize_excludes_a_project_not_known_to_the_memory_stack(
    tmp_path: Path, monkeypatch
) -> None:
    """A repo under a configured root with no memory in the store is not part
    of 'the fourteen files' the design describes — it has not been worked in
    through the harness yet.

    A sibling repo that *is* known keeps `known_keys` non-empty, so this
    exercises the per-candidate membership check rather than the short-circuit
    that skips scanning roots entirely when the store has nothing in it."""
    repos = tmp_path / "repos"
    repos.mkdir()
    store, _profile = _setup(tmp_path, monkeypatch, roots=[repos])
    known = _repo(repos, "widget")
    (known / "CLAUDE.md").write_text("line\n" * 5)
    _known_to_store(store, "widget")
    unseen = _repo(repos, "unseen")
    (unseen / "CLAUDE.md").write_text("line\n" * 300)
    # deliberately no _known_to_store(store, "unseen")

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "project:github.com/o/widget" in result.output
    assert "unseen" not in result.output


def test_rightsize_respects_configured_claude_md_thresholds(tmp_path: Path, monkeypatch) -> None:
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
        f'root = "{store}"\n\n'
        "[hooks.pre_tool_use]\n"
        "claude_md_max_lines = 10\n"
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    (profile / "CLAUDE.md").write_text("line\n" * 20)

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "1/1 over threshold" in result.output
    assert "> 10" in result.output


def test_rightsize_with_no_config_file_reports_nothing_and_does_not_crash(
    tmp_path: Path, monkeypatch
) -> None:
    """Parameterless smoke test: no --config knob exists on this command, so
    the only resolution path is the default one — an absent config.toml must
    degrade to an empty report, not a traceback."""
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path / "nowhere"))

    result = CliRunner().invoke(memory, ["rightsize"])

    assert result.exit_code == 0, result.output
    assert "No CLAUDE.md" in result.output
