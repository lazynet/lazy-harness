from pathlib import Path

from lazy_harness.migrate.detector import detect_claude_code


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
