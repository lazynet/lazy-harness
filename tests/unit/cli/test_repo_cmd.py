"""CLI gate for the single-file repository instruction contract."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

AGENTS_BODY = "# AGENTS.md — fixture\n\nEvery change goes through the gate.\n"


def _invoke(*args: str):
    from lazy_harness.cli.main import cli

    return CliRunner().invoke(cli, ["repo", "instructions", *args])


def test_a_compliant_repository_exits_zero(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(AGENTS_BODY)

    result = _invoke(str(tmp_path))

    assert result.exit_code == 0, result.output
    assert "portable repository contract" in result.output


def test_a_claude_md_exits_one_and_names_the_file(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(AGENTS_BODY)
    (tmp_path / "CLAUDE.md").write_text("# Claude-only rules\n")

    result = _invoke(str(tmp_path))

    assert result.exit_code == 1, result.output
    assert "claude-md-shadows-agents" in result.output
    assert "CLAUDE.md" in result.output


def test_the_path_argument_defaults_to_the_working_directory(tmp_path: Path) -> None:
    with CliRunner().isolated_filesystem(temp_dir=tmp_path) as cwd:
        (Path(cwd) / "AGENTS.md").write_text(AGENTS_BODY)
        result = _invoke()

    assert result.exit_code == 0, result.output
