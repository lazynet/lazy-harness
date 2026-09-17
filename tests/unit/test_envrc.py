"""Tests for direnv .envrc generator."""

from __future__ import annotations

from pathlib import Path


def test_render_creates_block_when_existing_is_none() -> None:
    from lazy_harness.core.envrc import BEGIN_MARKER, END_MARKER, render_envrc

    out = render_envrc("CLAUDE_CONFIG_DIR", Path("/home/foo/.claude-lazy"))
    assert BEGIN_MARKER in out
    assert END_MARKER in out
    assert 'export CLAUDE_CONFIG_DIR="/home/foo/.claude-lazy"' in out
    assert out.endswith("\n")


def test_render_replaces_existing_managed_block() -> None:
    from lazy_harness.core.envrc import render_envrc

    existing = (
        "# user prelude\n"
        "echo hello\n"
        "# >>> lazy-harness >>>\n"
        "# old content\n"
        'export CLAUDE_CONFIG_DIR="/old/path"\n'
        "# <<< lazy-harness <<<\n"
        "# user epilogue\n"
    )
    out = render_envrc("CLAUDE_CONFIG_DIR", Path("/new/path"), existing)
    assert "# user prelude" in out
    assert "echo hello" in out
    assert "# user epilogue" in out
    assert "/old/path" not in out
    assert 'export CLAUDE_CONFIG_DIR="/new/path"' in out
    # Markers appear exactly once after substitution
    assert out.count("# >>> lazy-harness >>>") == 1
    assert out.count("# <<< lazy-harness <<<") == 1


def test_render_appends_block_when_no_markers() -> None:
    from lazy_harness.core.envrc import BEGIN_MARKER, render_envrc

    existing = "# pre-existing user content\n_current_email=$(whoami)\n"
    out = render_envrc("CLAUDE_CONFIG_DIR", Path("/p"), existing)
    assert "_current_email=$(whoami)" in out
    assert BEGIN_MARKER in out
    assert out.index("_current_email") < out.index(BEGIN_MARKER)


def test_render_is_idempotent_on_repeated_calls() -> None:
    from lazy_harness.core.envrc import render_envrc

    first = render_envrc("CLAUDE_CONFIG_DIR", Path("/p"))
    second = render_envrc("CLAUDE_CONFIG_DIR", Path("/p"), first)
    third = render_envrc("CLAUDE_CONFIG_DIR", Path("/p"), second)
    assert first == second == third


def test_write_envrc_creates_new(tmp_path: Path) -> None:
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "myrepo"
    result = write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/h/.claude-x"))
    assert result.action == "created"
    assert result.path == root / ".envrc"
    assert result.path.is_file()
    assert "CLAUDE_CONFIG_DIR" in result.path.read_text()


def test_write_envrc_updates_existing(tmp_path: Path) -> None:
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "repo"
    root.mkdir()
    envrc = root / ".envrc"
    envrc.write_text(
        "# user line\n"
        "# >>> lazy-harness >>>\n"
        'export CLAUDE_CONFIG_DIR="/old"\n'
        "# <<< lazy-harness <<<\n"
    )
    result = write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/new"))
    assert result.action == "updated"
    content = envrc.read_text()
    assert "/new" in content
    assert "/old" not in content
    assert "# user line" in content


def test_write_envrc_unchanged_when_already_correct(tmp_path: Path) -> None:
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "repo"
    write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/x"))
    second = write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/x"))
    assert second.action == "unchanged"


def test_write_envrc_creates_root_dir_if_missing(tmp_path: Path) -> None:
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "deeply" / "nested" / "repo"
    result = write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/x"))
    assert result.action == "created"
    assert root.is_dir()


def test_write_envrc_works_for_arbitrary_env_var(tmp_path: Path) -> None:
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "repo"
    write_envrc(root, "OPENAI_HOME", Path("/openai"))
    content = (root / ".envrc").read_text()
    assert 'export OPENAI_HOME="/openai"' in content


def test_notice_carries_the_writing_version() -> None:
    """Decision 9: a deployed artifact declares the lazy-harness version that
    wrote it, so a stale `.envrc` can be told apart from a fresh one."""
    from lazy_harness import __version__
    from lazy_harness.core.envrc import render_envrc

    out = render_envrc("CLAUDE_CONFIG_DIR", Path("/p"))
    assert f"lazy-harness {__version__}" in out


def test_redeploy_at_same_version_is_byte_identical(tmp_path: Path) -> None:
    """Embedding lh_version must not break idempotence within one version."""
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "repo"
    write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/x"))
    first = (root / ".envrc").read_text()

    second_result = write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/x"))
    second = (root / ".envrc").read_text()

    assert second_result.action == "unchanged"
    assert first == second


# --- D7: two profiles with different agents on one root ---------------------


def test_write_envrc_twice_over_one_root_keeps_both_exports(tmp_path: Path) -> None:
    """The measured defect (specs/backlog.md D7): the second profile's write
    must not replace the first profile's export — both agents claim this root."""
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "repo"
    write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/h/.claude-work"))
    write_envrc(root, "CODEX_HOME", Path("/h/.codex-sandbox"))

    content = (root / ".envrc").read_text()
    assert 'export CLAUDE_CONFIG_DIR="/h/.claude-work"' in content
    assert 'export CODEX_HOME="/h/.codex-sandbox"' in content
    assert content.count("# >>> lazy-harness >>>") == 1


def test_write_envrc_third_identical_write_is_unchanged(tmp_path: Path) -> None:
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "repo"
    write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/h/.claude-work"))
    write_envrc(root, "CODEX_HOME", Path("/h/.codex-sandbox"))
    third = write_envrc(root, "CODEX_HOME", Path("/h/.codex-sandbox"))

    assert third.action == "unchanged"


def test_write_envrc_old_single_export_block_upgrades_in_place(tmp_path: Path) -> None:
    """A block written by a pre-D7 harness has no notion of multiple exports —
    a second profile's write must add to it, not treat it as foreign content."""
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "repo"
    root.mkdir()
    envrc = root / ".envrc"
    envrc.write_text(
        "# >>> lazy-harness >>>\n"
        "# Managed by `lh profile envrc` (lazy-harness 0.70.0) — do not edit this block by hand.\n"
        'export CLAUDE_CONFIG_DIR="/h/.claude-work"\n'
        "# <<< lazy-harness <<<\n"
    )

    result = write_envrc(root, "CODEX_HOME", Path("/h/.codex-sandbox"))

    assert result.action == "updated"
    content = envrc.read_text()
    assert 'export CLAUDE_CONFIG_DIR="/h/.claude-work"' in content
    assert 'export CODEX_HOME="/h/.codex-sandbox"' in content


def test_multi_export_block_orders_exports_deterministically_by_env_var(
    tmp_path: Path,
) -> None:
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "repo"
    write_envrc(root, "CODEX_HOME", Path("/h/.codex-sandbox"))
    write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/h/.claude-work"))

    content = (root / ".envrc").read_text()
    assert content.index("CLAUDE_CONFIG_DIR") < content.index("CODEX_HOME")


def test_rewriting_the_same_env_var_updates_its_config_dir_only(tmp_path: Path) -> None:
    from lazy_harness.core.envrc import write_envrc

    root = tmp_path / "repo"
    write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/old"))
    write_envrc(root, "CODEX_HOME", Path("/h/.codex-sandbox"))
    write_envrc(root, "CLAUDE_CONFIG_DIR", Path("/new"))

    content = (root / ".envrc").read_text()
    assert 'export CLAUDE_CONFIG_DIR="/new"' in content
    assert "/old" not in content
    assert 'export CODEX_HOME="/h/.codex-sandbox"' in content
