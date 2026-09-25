"""CLI gate for the single-file repository instruction contract."""

from __future__ import annotations

import json
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


def test_several_repositories_are_checked_in_one_run(tmp_path: Path) -> None:
    clean = tmp_path / "clean"
    shadowed = tmp_path / "shadowed"
    for repo in (clean, shadowed):
        repo.mkdir()
        (repo / "AGENTS.md").write_text(AGENTS_BODY)
    (shadowed / "CLAUDE.md").write_text("# Claude-only rules\n")

    result = _invoke(str(clean), str(shadowed))

    assert result.exit_code == 1, result.output
    assert f"✓ {clean}" in result.output
    assert f"✗ {shadowed}" in result.output
    assert "claude-md-shadows-agents" in result.output


def test_several_clean_repositories_exit_zero(tmp_path: Path) -> None:
    repos = [tmp_path / "a", tmp_path / "b"]
    for repo in repos:
        repo.mkdir()
        (repo / "AGENTS.md").write_text(AGENTS_BODY)

    result = _invoke(*(str(r) for r in repos))

    assert result.exit_code == 0, result.output
    assert result.output.count("✓") == 2


def _manifest(tmp_path: Path, repositories: list[dict[str, object]]) -> Path:
    path = tmp_path / "fleet.json"
    path.write_text(json.dumps({"repositories": repositories}))
    return path


def test_manifest_classifies_repositories_and_preserves_active_failure(tmp_path: Path) -> None:
    active = tmp_path / "active"
    deferred = tmp_path / "deferred"
    upstream = tmp_path / "upstream"
    for repo in (active, deferred, upstream):
        repo.mkdir()
        (repo / "CLAUDE.md").write_text("rules")
    manifest = _manifest(
        tmp_path,
        [
            {"path": "active", "status": "active"},
            {"path": "deferred", "status": "deferred"},
            {"path": "upstream", "status": "upstream"},
        ],
    )

    result = _invoke("--manifest", str(manifest))

    assert result.exit_code == 1, result.output
    assert "active" in result.output and "claude-md-shadows-agents" in result.output
    assert "deferred" in result.output and "upstream" in result.output


def test_manifest_data_exception_is_exact_and_nested_shadow_still_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(AGENTS_BODY)
    for folder in ("fixtures", "nested"):
        directory = repo / folder
        directory.mkdir()
        (directory / "CLAUDE.md").write_text("sample")
    manifest = _manifest(
        tmp_path, [{"path": "repo", "status": "active", "instruction_data": ["fixtures/CLAUDE.md"]}]
    )

    result = _invoke("--manifest", str(manifest))

    assert result.exit_code == 1, result.output
    assert "nested/CLAUDE.md" in result.output
    assert "fixtures/CLAUDE.md" not in result.output


def test_manifest_rejects_unknown_status_and_traversal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for entry in (
        {"path": "repo", "status": "unknown"},
        {"path": "../outside", "status": "active"},
        {"path": "repo", "status": "active", "instruction_data": ["../CLAUDE.md"]},
        {"path": "repo", "status": "active", "instruction_data": ["fixtures/OTHER.md"]},
    ):
        result = _invoke("--manifest", str(_manifest(tmp_path, [entry])))
        assert result.exit_code != 0, result.output
        assert "Invalid" in result.output or "invalid" in result.output


def test_manifest_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    manifest = _manifest(tmp_path, [{"path": "escape", "status": "active"}])

    result = _invoke("--manifest", str(manifest))

    assert result.exit_code != 0, result.output
    assert "invalid" in result.output.lower()


def test_deferred_repository_still_reports_ancestor_shadow(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("ancestor")
    deferred = tmp_path / "deferred"
    deferred.mkdir()
    (deferred / "CLAUDE.md").write_text("migration pending")
    manifest = _manifest(tmp_path, [{"path": "deferred", "status": "deferred"}])

    result = _invoke("--manifest", str(manifest))

    assert result.exit_code == 1, result.output
    assert "ancestor-claude-md-shadows-agents" in result.output


def test_declared_deferral_without_ancestor_shadow_passes(tmp_path: Path) -> None:
    deferred = tmp_path / "deferred"
    deferred.mkdir()
    (deferred / "CLAUDE.md").write_text("migration pending")
    manifest = _manifest(tmp_path, [{"path": "deferred", "status": "deferred"}])

    result = _invoke("--manifest", str(manifest))

    assert result.exit_code == 0, result.output
    assert "deferred" in result.output


def test_manifest_rejects_root_claude_md_as_instruction_data(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(AGENTS_BODY)
    (repo / "CLAUDE.md").write_text("shadow")
    manifest = _manifest(
        tmp_path, [{"path": "repo", "status": "active", "instruction_data": ["CLAUDE.md"]}]
    )

    result = _invoke("--manifest", str(manifest))

    assert result.exit_code == 2, result.output
    assert "root CLAUDE.md" in result.output


def test_manifest_rejects_alias_of_root_claude_md(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(AGENTS_BODY)
    (repo / "CLAUDE.md").write_text("shadow")
    (repo / "alias").symlink_to(repo, target_is_directory=True)
    manifest = _manifest(
        tmp_path, [{"path": "repo", "status": "active", "instruction_data": ["alias/CLAUDE.md"]}]
    )

    result = _invoke("--manifest", str(manifest))

    assert result.exit_code == 2, result.output
    assert "root CLAUDE.md" in result.output


def test_manifest_rejects_instruction_data_symlink_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(AGENTS_BODY)
    (tmp_path / "CLAUDE.md").write_text("ancestor")
    (repo / "CLAUDE.md").symlink_to(tmp_path / "CLAUDE.md")
    manifest = _manifest(
        tmp_path, [{"path": "repo", "status": "active", "instruction_data": ["CLAUDE.md"]}]
    )

    result = _invoke("--manifest", str(manifest))

    assert result.exit_code == 2, result.output
    assert "invalid" in result.output.lower()


def test_declared_nested_data_is_shadow_from_inside_its_directory(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    fixture = repo / "fixtures"
    nested = fixture / "subdir"
    nested.mkdir(parents=True)
    (repo / "AGENTS.md").write_text(AGENTS_BODY)
    (fixture / "CLAUDE.md").write_text("stored sample")
    manifest = _manifest(
        tmp_path, [{"path": "repo", "status": "active", "instruction_data": ["fixtures/CLAUDE.md"]}]
    )
    monkeypatch.chdir(nested)

    result = _invoke("--manifest", str(manifest))

    assert result.exit_code == 1, result.output
    assert "fixtures/CLAUDE.md" in result.output
    assert "claude-md-shadows-agents" in result.output


def test_declared_nested_data_does_not_hide_ancestor_from_inside(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "CLAUDE.md").write_text("ancestor")
    repo = tmp_path / "repo"
    fixture = repo / "fixtures"
    fixture.mkdir(parents=True)
    (repo / "AGENTS.md").write_text(AGENTS_BODY)
    (fixture / "CLAUDE.md").write_text("stored sample")
    manifest = _manifest(
        tmp_path, [{"path": "repo", "status": "active", "instruction_data": ["fixtures/CLAUDE.md"]}]
    )
    monkeypatch.chdir(fixture)

    result = _invoke("--manifest", str(manifest))

    assert result.exit_code == 1, result.output
    assert "ancestor-claude-md-shadows-agents" in result.output
    assert "fixtures/CLAUDE.md" in result.output


def test_manifest_reports_malformed_path_as_bad_parameter(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for raw in ("repo/\x00bad", "loop"):
        (tmp_path / "loop").symlink_to("loop") if raw == "loop" else None
        manifest = _manifest(tmp_path, [{"path": raw, "status": "active"}])
        result = _invoke("--manifest", str(manifest))
        assert result.exit_code == 2, result.output
        assert "Invalid value for --manifest" in result.output
        assert result.exception is not None
