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

    def fake_invoke(prompt: str, backend: object, model: str, timeout: int) -> str:
        captured["prompt"] = prompt
        captured["backend"] = backend
        captured["model"] = model
        return "## Proposed additions\n- prefer uv over pip everywhere"

    monkeypatch.setattr("lazy_harness.cli.memory_cmd._invoke_llm", fake_invoke)

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

    def fake_invoke(prompt: str, backend: object, model: str, timeout: int) -> str:
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr("lazy_harness.cli.memory_cmd._invoke_llm", fake_invoke)

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


def test_consolidate_resolves_backend_from_config(tmp_path: Path, monkeypatch) -> None:
    """ADR-033: consolidate uses the [compound_loop].backend from config.toml."""
    from lazy_harness.cli import memory_cmd as mod

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[compound_loop]
backend = "ollama"
"""
    )
    monkeypatch.setattr(mod, "config_file", lambda: cfg_file)

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    _write_jsonl(memory_dir / "decisions.jsonl", [{"decision": "x"}])

    captured: dict = {}

    def fake_invoke(prompt: str, backend: object, model: str, timeout: int) -> str:
        captured["backend"] = backend
        return "ok"

    monkeypatch.setattr(mod, "_invoke_llm", fake_invoke)

    runner = CliRunner()
    result = runner.invoke(mod.memory, ["consolidate", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output

    from lazy_harness.llm.openai_compat import OpenAICompatibleBackend

    assert isinstance(captured["backend"], OpenAICompatibleBackend)


def test_consolidate_model_defaults_to_compound_loop_config(tmp_path: Path, monkeypatch) -> None:
    """No --model flag → model resolves from [compound_loop].model, like the worker."""
    from lazy_harness.cli import memory_cmd as mod

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[compound_loop]
backend = "ollama"
model = "llama3.2:3b"
"""
    )
    monkeypatch.setattr(mod, "config_file", lambda: cfg_file)

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    _write_jsonl(memory_dir / "decisions.jsonl", [{"decision": "x"}])

    captured: dict = {}

    def fake_invoke(prompt: str, backend: object, model: str, timeout: int) -> str:
        captured["model"] = model
        return "ok"

    monkeypatch.setattr(mod, "_invoke_llm", fake_invoke)

    runner = CliRunner()
    result = runner.invoke(mod.memory, ["consolidate", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output
    assert captured["model"] == "llama3.2:3b"


def test_consolidate_model_flag_overrides_config(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli import memory_cmd as mod

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[compound_loop]
backend = "ollama"
model = "llama3.2:3b"
"""
    )
    monkeypatch.setattr(mod, "config_file", lambda: cfg_file)

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    _write_jsonl(memory_dir / "decisions.jsonl", [{"decision": "x"}])

    captured: dict = {}

    def fake_invoke(prompt: str, backend: object, model: str, timeout: int) -> str:
        captured["model"] = model
        return "ok"

    monkeypatch.setattr(mod, "_invoke_llm", fake_invoke)

    runner = CliRunner()
    result = runner.invoke(
        mod.memory,
        ["consolidate", "--memory-dir", str(memory_dir), "--model", "qwen3:8b"],
    )
    assert result.exit_code == 0, result.output
    assert captured["model"] == "qwen3:8b"


def test_consolidate_falls_back_to_claude_backend_without_config(
    tmp_path: Path, monkeypatch
) -> None:
    from lazy_harness.cli import memory_cmd as mod

    monkeypatch.setattr(mod, "config_file", lambda: tmp_path / "missing" / "config.toml")

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    _write_jsonl(memory_dir / "decisions.jsonl", [{"decision": "x"}])

    captured: dict = {}

    def fake_invoke(prompt: str, backend: object, model: str, timeout: int) -> str:
        captured["backend"] = backend
        captured["model"] = model
        return "ok"

    monkeypatch.setattr(mod, "_invoke_llm", fake_invoke)

    runner = CliRunner()
    result = runner.invoke(mod.memory, ["consolidate", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output

    from lazy_harness.llm.claude import ClaudeBackend

    assert isinstance(captured["backend"], ClaudeBackend)
    assert captured["model"] == ClaudeBackend().default_model()


# --- proposals lifecycle (Phase 3c) ---

PROPOSALS_TEXT = """\
<!-- claude-md proposals (append-only). Review and merge into CLAUDE.md or discard. -->

## 2026-05-20T10:00:00-03:00

- **Rule:** Run a docs coherence pass before each release
  - **Rationale:** Docs drifted twice before releases
- **Rule:** Never amend published commits

## 2026-05-27T09:30:00-03:00

- **Rule:** Verify persistence with explicit file output
  - **Rationale:** A write was claimed that never happened
"""

ARCHIVED_ONLY_TEXT = """\
<!-- claude-md proposals (append-only). Review and merge into CLAUDE.md or discard. -->

<!-- ARCHIVED 2026-06-11: both pending proposals were ACCEPTED and merged
     via PR #93. No pending proposals. -->
"""


def _write_proposals(memory_dir: Path, text: str = PROPOSALS_TEXT) -> Path:
    memory_dir.mkdir(parents=True, exist_ok=True)
    path = memory_dir / "claude-md.proposal.md"
    path.write_text(text)
    return path


def test_parse_proposals_extracts_rules_with_timestamps() -> None:
    from lazy_harness.cli.memory_cmd import parse_proposals

    proposals = parse_proposals(PROPOSALS_TEXT)
    assert len(proposals) == 3
    assert proposals[0].timestamp == "2026-05-20T10:00:00-03:00"
    assert proposals[0].rule == "Run a docs coherence pass before each release"
    assert proposals[0].rationale == "Docs drifted twice before releases"
    assert proposals[1].rule == "Never amend published commits"
    assert proposals[1].rationale == ""
    assert proposals[2].timestamp == "2026-05-27T09:30:00-03:00"
    assert proposals[2].rule == "Verify persistence with explicit file output"


def test_parse_proposals_tolerates_archived_comments_only_file() -> None:
    from lazy_harness.cli.memory_cmd import parse_proposals

    assert parse_proposals(ARCHIVED_ONLY_TEXT) == []


def test_parse_proposals_empty_text() -> None:
    from lazy_harness.cli.memory_cmd import parse_proposals

    assert parse_proposals("") == []


def test_proposals_list_shows_numbered_pending(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    runner = CliRunner()
    result = runner.invoke(memory, ["proposals", "list", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output
    assert "2026-05-20" in result.output
    assert "2026-05-27" in result.output
    assert "Run a docs coherence pass" in result.output
    assert "3" in result.output  # third index present


def test_proposals_list_empty_prints_friendly_message(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    runner = CliRunner()
    result = runner.invoke(memory, ["proposals", "list", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output
    assert "No pending claude-md proposals" in result.output


def test_proposals_list_archived_only_counts_as_empty(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir, ARCHIVED_ONLY_TEXT)
    runner = CliRunner()
    result = runner.invoke(memory, ["proposals", "list", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output
    assert "No pending claude-md proposals" in result.output


def test_proposals_accept_moves_entry_and_prints_rule(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    pending = _write_proposals(memory_dir)
    runner = CliRunner()
    result = runner.invoke(memory, ["proposals", "accept", "1", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output

    # Full rule text printed with the human-gate hint
    assert "Run a docs coherence pass before each release" in result.output
    assert "MEMORY.md" in result.output
    assert "CLAUDE.md" in result.output

    # Removed from pending, others intact
    remaining = pending.read_text()
    assert "Run a docs coherence pass" not in remaining
    assert "Never amend published commits" in remaining
    assert "Verify persistence with explicit file output" in remaining

    # Appended to accepted registry with acceptance date
    accepted = (memory_dir / "claude-md.accepted.md").read_text()
    assert "- **Rule:** Run a docs coherence pass before each release" in accepted
    assert "accepted: " in accepted
    assert "## 2026-05-20T10:00:00-03:00" in accepted


def test_proposals_accept_is_append_only(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    runner = CliRunner()
    r1 = runner.invoke(memory, ["proposals", "accept", "1", "--memory-dir", str(memory_dir)])
    r2 = runner.invoke(memory, ["proposals", "accept", "1", "--memory-dir", str(memory_dir)])
    assert r1.exit_code == 0 and r2.exit_code == 0
    accepted = (memory_dir / "claude-md.accepted.md").read_text()
    assert "Run a docs coherence pass before each release" in accepted
    assert "Never amend published commits" in accepted


def test_proposals_accept_out_of_range_errors(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    runner = CliRunner()
    result = runner.invoke(memory, ["proposals", "accept", "9", "--memory-dir", str(memory_dir)])
    assert result.exit_code != 0
    assert "9" in result.output


def test_proposals_reject_records_date_and_reason(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    pending = _write_proposals(memory_dir)
    runner = CliRunner()
    result = runner.invoke(
        memory,
        [
            "proposals",
            "reject",
            "2",
            "--reason",
            "too strict for this repo",
            "--memory-dir",
            str(memory_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    remaining = pending.read_text()
    assert "Never amend published commits" not in remaining
    assert "Run a docs coherence pass" in remaining

    rejected = (memory_dir / "claude-md.rejected.md").read_text()
    assert "- **Rule:** Never amend published commits" in rejected
    assert "rejected: " in rejected
    assert "reason: too strict for this repo" in rejected


def test_proposals_reject_requires_reason(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    runner = CliRunner()
    result = runner.invoke(memory, ["proposals", "reject", "1", "--memory-dir", str(memory_dir)])
    assert result.exit_code != 0


def test_proposals_accept_drops_header_when_section_empties(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    pending = _write_proposals(memory_dir)
    runner = CliRunner()
    # Section 2026-05-27 has a single rule (index 3)
    result = runner.invoke(memory, ["proposals", "accept", "3", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output
    remaining = pending.read_text()
    assert "## 2026-05-27T09:30:00-03:00" not in remaining
    assert "## 2026-05-20T10:00:00-03:00" in remaining


def test_proposals_default_memory_dir_follows_agent_runtime_dir(
    tmp_path: Path, monkeypatch
) -> None:
    from lazy_harness.cli.memory_cmd import memory

    agent_dir = tmp_path / "agent"
    repo = tmp_path / "repo"
    repo.mkdir()
    encoded = "-" + str(repo).replace("/", "-").lstrip("-")
    memory_dir = agent_dir / "projects" / encoded / "memory"
    _write_proposals(memory_dir)

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(agent_dir))
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path / "no-config"))
    monkeypatch.chdir(repo)

    runner = CliRunner()
    result = runner.invoke(memory, ["proposals", "list"])
    assert result.exit_code == 0, result.output
    assert "Run a docs coherence pass" in result.output
