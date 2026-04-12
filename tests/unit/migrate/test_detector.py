from pathlib import Path

from lazy_harness.migrate.detector import detect_claude_code, detect_lazy_claudecode


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
