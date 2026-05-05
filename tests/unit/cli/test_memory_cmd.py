"""Tests for `lh memory cross-profile-check` (ADR-030 G7)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from click.testing import CliRunner


def _make_profile(profile_dir: Path, projects: dict[str, str]) -> None:
    """Create a fake `<profile>/projects/<key>/memory/MEMORY.md` tree."""
    for key, content in projects.items():
        memory_dir = profile_dir / "projects" / key / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "MEMORY.md").write_text(content)


def test_enumerate_profile_projects_lists_keys_with_memory_md(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import enumerate_profile_projects

    profile_dir = tmp_path / "profile"
    _make_profile(
        profile_dir,
        {
            "-Users-x-repos-foo": "alpha",
            "-Users-x-repos-bar": "beta",
        },
    )
    result = enumerate_profile_projects(profile_dir)
    assert set(result.keys()) == {"-Users-x-repos-foo", "-Users-x-repos-bar"}
    foo = result["-Users-x-repos-foo"]
    assert foo["memory_md_lines"] == 1
    assert foo["memory_md_sha"] == hashlib.sha256(b"alpha").hexdigest()[:12]


def test_enumerate_profile_projects_returns_empty_for_missing_dir(
    tmp_path: Path,
) -> None:
    from lazy_harness.cli.memory_cmd import enumerate_profile_projects

    assert enumerate_profile_projects(tmp_path / "missing") == {}


def test_enumerate_profile_projects_skips_keys_without_memory_md(
    tmp_path: Path,
) -> None:
    from lazy_harness.cli.memory_cmd import enumerate_profile_projects

    profile_dir = tmp_path / "p"
    (profile_dir / "projects" / "key1" / "memory").mkdir(parents=True)
    # No MEMORY.md → key1 should not appear
    result = enumerate_profile_projects(profile_dir)
    assert result == {}


def test_find_cross_profile_divergences_flags_shared_keys_with_different_content(
    tmp_path: Path,
) -> None:
    from lazy_harness.cli.memory_cmd import find_cross_profile_divergences

    profile_data = {
        "lazy": {
            "-foo": {"memory_md_sha": "aaa", "memory_md_lines": 10},
            "-bar": {"memory_md_sha": "bbb", "memory_md_lines": 5},
        },
        "flex": {
            "-foo": {"memory_md_sha": "ccc", "memory_md_lines": 12},  # divergent
            "-baz": {"memory_md_sha": "ddd", "memory_md_lines": 7},
        },
    }
    divergences = find_cross_profile_divergences(profile_data)
    keys = {d["project_key"] for d in divergences}
    assert "-foo" in keys
    assert "-bar" not in keys
    assert "-baz" not in keys


def test_find_cross_profile_divergences_ignores_matching_keys(
    tmp_path: Path,
) -> None:
    from lazy_harness.cli.memory_cmd import find_cross_profile_divergences

    profile_data = {
        "lazy": {"-foo": {"memory_md_sha": "aaa", "memory_md_lines": 10}},
        "flex": {"-foo": {"memory_md_sha": "aaa", "memory_md_lines": 10}},
    }
    assert find_cross_profile_divergences(profile_data) == []


def test_memory_group_registered_on_top_level_cli() -> None:
    from lazy_harness.cli.main import cli

    assert "memory" in cli.commands


def _write_jsonl(path: Path, records: list[dict]) -> None:
    import json as _json

    with open(path, "w") as f:
        for r in records:
            f.write(_json.dumps(r) + "\n")


def test_consolidate_reads_jsonl_and_invokes_claude(tmp_path: Path, monkeypatch) -> None:
    """Reads decisions.jsonl + failures.jsonl, builds prompt, calls invoke."""
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    _write_jsonl(
        memory_dir / "decisions.jsonl",
        [
            {"ts": "2026-05-01", "decision": "use uv for deps"},
            {"ts": "2026-05-02", "decision": "ruff over black"},
        ],
    )
    _write_jsonl(
        memory_dir / "failures.jsonl",
        [{"ts": "2026-05-03", "failure": "missed strict mypy"}],
    )

    captured: dict = {}

    def fake_invoke(prompt: str, model: str, timeout: int) -> str:
        captured["prompt"] = prompt
        captured["model"] = model
        return "## Proposed additions\n- prefer uv over pip everywhere"

    monkeypatch.setattr("lazy_harness.cli.memory_cmd._invoke_claude", fake_invoke)

    runner = CliRunner()
    result = runner.invoke(memory, ["consolidate", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output
    assert "Proposed additions" in result.output
    assert "use uv for deps" in captured["prompt"]
    assert "missed strict mypy" in captured["prompt"]


def test_consolidate_exits_with_message_when_no_jsonl_present(
    tmp_path: Path,
) -> None:
    from lazy_harness.cli.memory_cmd import memory

    runner = CliRunner()
    result = runner.invoke(memory, ["consolidate", "--memory-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "no entries" in result.output.lower()


def test_consolidate_respects_last_n_flag(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    _write_jsonl(
        memory_dir / "decisions.jsonl",
        [{"decision": f"d{i}"} for i in range(20)],
    )

    captured: dict = {}

    def fake_invoke(prompt: str, model: str, timeout: int) -> str:
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr("lazy_harness.cli.memory_cmd._invoke_claude", fake_invoke)

    runner = CliRunner()
    result = runner.invoke(
        memory,
        ["consolidate", "--memory-dir", str(memory_dir), "--last", "5"],
    )
    assert result.exit_code == 0, result.output
    assert "d19" in captured["prompt"]
    assert "d15" in captured["prompt"]
    assert "d14" not in captured["prompt"]


def test_cross_profile_check_cli_prints_report(tmp_path: Path, monkeypatch) -> None:
    """Black-box: `lh memory cross-profile-check` exits 0 and prints summary."""
    from lazy_harness.cli.memory_cmd import memory

    # Two profile dirs with one overlapping divergent project
    lazy_dir = tmp_path / ".claude-lazy"
    flex_dir = tmp_path / ".claude-flex"
    _make_profile(lazy_dir, {"-Users-x-repos-foo": "lazy version"})
    _make_profile(flex_dir, {"-Users-x-repos-foo": "flex version"})

    config_path = tmp_path / "config.toml"
    config_path.write_text(f"""[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "lazy"

[profiles.lazy]
config_dir = "{lazy_dir}"
roots = ["~"]

[profiles.flex]
config_dir = "{flex_dir}"
roots = ["~"]
""")

    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: config_path)
    monkeypatch.setattr("lazy_harness.cli.memory_cmd.config_file", lambda: config_path)

    runner = CliRunner()
    result = runner.invoke(memory, ["cross-profile-check"])
    assert result.exit_code == 0, result.output
    assert "lazy" in result.output
    assert "flex" in result.output
    assert "-Users-x-repos-foo" in result.output
    assert "diverge" in result.output.lower()
