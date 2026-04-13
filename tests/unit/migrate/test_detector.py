from pathlib import Path

from lazy_harness.migrate.detector import (
    detect_claude_code,
    detect_deployed_scripts,
    detect_launch_agents,
    detect_lazy_claudecode,
    detect_qmd,
    detect_state,
)


def test_detect_claude_code_empty_dir_returns_none(tmp_path: Path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    assert detect_claude_code(claude_dir) is None


def test_detect_claude_code_with_settings(tmp_path: Path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text("{}")
    result = detect_claude_code(claude_dir)
    assert result is not None
    assert result.path == claude_dir
    assert result.has_settings is True
    assert result.has_claude_md is False


def test_detect_claude_code_nonexistent_dir(tmp_path: Path):
    assert detect_claude_code(tmp_path / "nope") is None


def test_detect_lazy_claudecode_no_profiles(tmp_path: Path):
    assert detect_lazy_claudecode(tmp_path) is None


def test_detect_lazy_claudecode_single_profile(tmp_path: Path):
    lazy_dir = tmp_path / ".claude-lazy"
    lazy_dir.mkdir()
    (lazy_dir / "settings.json").write_text("{}")
    (lazy_dir / "CLAUDE.md").write_text("# lazy")
    (lazy_dir / "skills").mkdir()

    result = detect_lazy_claudecode(tmp_path)
    assert result is not None
    assert result.profiles == ["lazy"]
    assert result.claude_dirs["lazy"] == lazy_dir
    assert result.settings_paths["lazy"] == lazy_dir / "settings.json"
    assert result.skills_dirs["lazy"] == lazy_dir / "skills"


def test_detect_lazy_claudecode_multi_profile(tmp_path: Path):
    for name in ("lazy", "flex"):
        d = tmp_path / f".claude-{name}"
        d.mkdir()
        (d / "settings.json").write_text("{}")

    result = detect_lazy_claudecode(tmp_path)
    assert result is not None
    assert sorted(result.profiles) == ["flex", "lazy"]


def test_detect_deployed_scripts_finds_lcc_symlinks(tmp_path: Path):
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    target = tmp_path / "repo" / "scripts" / "lcc-status"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\n")
    target.chmod(0o755)
    (bin_dir / "lcc-status").symlink_to(target)
    (bin_dir / "lcc-dangling").symlink_to(tmp_path / "missing")
    (bin_dir / "unrelated").write_text("#!/bin/sh\n")

    scripts = detect_deployed_scripts(bin_dir)
    names = sorted(s.name for s in scripts)
    assert names == ["lcc-dangling", "lcc-status"]
    by_name = {s.name: s for s in scripts}
    assert by_name["lcc-status"].target == target
    assert by_name["lcc-dangling"].target is None


def test_detect_launch_agents_filters_com_lazy(tmp_path: Path):
    la_dir = tmp_path / "LaunchAgents"
    la_dir.mkdir()
    (la_dir / "com.lazy.status.plist").write_text("<plist/>")
    (la_dir / "com.lazy.sessions.plist").write_text("<plist/>")
    (la_dir / "com.lazynet.example.plist").write_text("<plist/>")
    (la_dir / "com.apple.other.plist").write_text("<plist/>")

    agents = detect_launch_agents(la_dir)
    labels = sorted(a.label for a in agents)
    assert labels == ["com.lazy.sessions", "com.lazy.status", "com.lazynet.example"]


def test_detect_qmd_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert detect_qmd() is False


def test_detect_qmd_present(monkeypatch):
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/local/bin/qmd" if name == "qmd" else None,
    )
    assert detect_qmd() is True


def test_detect_state_empty_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda name: None)
    state = detect_state(
        home=tmp_path,
        config_file_override=tmp_path / "nonexistent.toml",
        bin_dir=tmp_path / ".local" / "bin",
        launch_agents_dir=tmp_path / "LaunchAgents",
    )
    assert state.has_existing_setup() is False


def test_detect_state_full(tmp_path: Path, monkeypatch):
    # lazy-claudecode profile
    lazy = tmp_path / ".claude-lazy"
    lazy.mkdir()
    (lazy / "settings.json").write_text("{}")

    # lazy-harness previous config
    cfg_dir = tmp_path / ".config" / "lazy-harness"
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.toml"
    cfg_file.write_text("")

    # deployed script
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    target = tmp_path / "repo" / "lcc-status"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\n")
    (bin_dir / "lcc-status").symlink_to(target)

    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/qmd" if name == "qmd" else None,
    )

    state = detect_state(
        home=tmp_path,
        config_file_override=cfg_file,
        bin_dir=bin_dir,
        launch_agents_dir=tmp_path / "LaunchAgents",
    )
    assert state.lazy_claudecode is not None
    assert state.lazy_harness_config == cfg_file
    assert len(state.deployed_scripts) == 1
    assert state.qmd_available is True
    assert state.has_existing_setup() is True
