"""Tests for the `lh memory` command group."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.core.proposals import parse_proposals
from lazy_harness.llm.invoke import InferenceError, InferenceResult


def _stub_run_inference(monkeypatch, mod, fn) -> None:
    """Monkeypatch `run_inference` in `mod` (memory_cmd) with the old
    `_invoke_llm(prompt, backend, model, timeout) -> str | None` contract:
    `fn(prompt, model, timeout) -> str | None`, `None`/`""` means failure.
    `backend` on the returned InferenceResult carries the resolved role's
    backend type so tests can assert on it the way they used to assert on a
    constructed backend instance.
    """

    def fake_run_inference(prompt, *, role, cfg, timeout, schema=None, model=None):
        from lazy_harness.llm.roles import resolve_role

        target = resolve_role(cfg, role)
        resolved_model = model or target.model
        output = fn(prompt, resolved_model, timeout)
        if not output:
            return InferenceResult(
                output="",
                success=False,
                model=resolved_model,
                backend=target.type,
                duration_ms=0,
                error=InferenceError(kind="empty", message="backend returned no output"),
            )
        return InferenceResult(
            output=output,
            success=True,
            model=resolved_model,
            backend=target.type,
            duration_ms=0,
            error=None,
        )

    monkeypatch.setattr(mod, "run_inference", fake_run_inference)


def _make_profile(profile_dir: Path, projects: dict[str, str]) -> None:
    """Create a fake `<profile>/projects/<key>/memory/MEMORY.md` tree."""
    for key, content in projects.items():
        memory_dir = profile_dir / "projects" / key / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "MEMORY.md").write_text(content)


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
    from lazy_harness.cli import memory_cmd as mod

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

    _stub_run_inference(monkeypatch, mod, fake_invoke)

    runner = CliRunner()
    result = runner.invoke(mod.memory, ["consolidate", "--memory-dir", str(memory_dir)])
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
    from lazy_harness.cli import memory_cmd as mod

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

    _stub_run_inference(monkeypatch, mod, fake_invoke)

    runner = CliRunner()
    result = runner.invoke(
        mod.memory,
        ["consolidate", "--memory-dir", str(memory_dir), "--last", "5"],
    )
    assert result.exit_code == 0, result.output
    assert "d19" in captured["prompt"]
    assert "d15" in captured["prompt"]
    assert "d14" not in captured["prompt"]


class _RecordingBackend:
    """A backend stub for asserting on the type run_inference resolved to,
    without hitting a real subprocess or HTTP call."""

    def __init__(self, model: str = "stub-default") -> None:
        self._model = model

    def default_model(self) -> str:
        return self._model

    def complete(self, prompt: str, model: str, timeout: int, *, schema=None) -> str:
        return "ok"


def test_consolidate_resolves_backend_from_config(tmp_path: Path, monkeypatch) -> None:
    """ADR-039: consolidate resolves the `distill` role, which falls back to
    [compound_loop].backend from config.toml via the deprecated bridge."""
    from lazy_harness.cli import memory_cmd as mod
    from lazy_harness.llm import invoke as invoke_mod

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

    built: dict = {}

    def fake_build_backend(**kwargs):
        built.update(kwargs)
        return _RecordingBackend()

    monkeypatch.setattr(invoke_mod, "build_backend", fake_build_backend)

    runner = CliRunner()
    result = runner.invoke(mod.memory, ["consolidate", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output
    assert built["type"] == "ollama"


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

    def fake_invoke(prompt: str, model: str, timeout: int) -> str:
        captured["model"] = model
        return "ok"

    _stub_run_inference(monkeypatch, mod, fake_invoke)

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

    def fake_invoke(prompt: str, model: str, timeout: int) -> str:
        captured["model"] = model
        return "ok"

    _stub_run_inference(monkeypatch, mod, fake_invoke)

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
    from lazy_harness.llm import invoke as invoke_mod

    monkeypatch.setattr(mod, "config_file", lambda: tmp_path / "missing" / "config.toml")

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    _write_jsonl(memory_dir / "decisions.jsonl", [{"decision": "x"}])

    built: dict = {}

    def fake_build_backend(**kwargs):
        built.update(kwargs)
        return _RecordingBackend()

    monkeypatch.setattr(invoke_mod, "build_backend", fake_build_backend)

    runner = CliRunner()
    result = runner.invoke(mod.memory, ["consolidate", "--memory-dir", str(memory_dir)])
    assert result.exit_code == 0, result.output

    assert built["type"] == "claude"


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


def _linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Build a main checkout plus a linked worktree; return (repo_root, worktree)."""
    repo = tmp_path / "repo"
    (repo / ".git" / "worktrees" / "wt").mkdir(parents=True)
    worktree = repo / ".worktrees" / "wt"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {repo / '.git' / 'worktrees' / 'wt'}\n")
    return repo, worktree


def test_project_memory_dir_resolves_worktree_to_main_checkout(tmp_path: Path, monkeypatch) -> None:
    """Proposals accepted from a worktree must land on the main checkout's file."""
    from lazy_harness.cli.memory_cmd import _project_memory_dir

    runtime = tmp_path / "runtime"
    monkeypatch.setattr("lazy_harness.core.paths.agent_runtime_dir", lambda _agent: runtime)
    monkeypatch.setattr(
        "lazy_harness.cli.memory_cmd.config_file", lambda: tmp_path / "missing.toml"
    )
    repo, worktree = _linked_worktree(tmp_path)
    monkeypatch.chdir(worktree)

    encoded = "-" + str(repo).replace("/", "-").lstrip("-")
    assert _project_memory_dir() == runtime / "projects" / encoded / "memory"


def test_project_memory_dir_uses_cwd_outside_a_worktree(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.memory_cmd import _project_memory_dir

    runtime = tmp_path / "runtime"
    monkeypatch.setattr("lazy_harness.core.paths.agent_runtime_dir", lambda _agent: runtime)
    monkeypatch.setattr(
        "lazy_harness.cli.memory_cmd.config_file", lambda: tmp_path / "missing.toml"
    )
    repo = tmp_path / "plain"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(repo)

    encoded = "-" + str(repo).replace("/", "-").lstrip("-")
    assert _project_memory_dir() == runtime / "projects" / encoded / "memory"


def test_project_memory_dir_resolves_into_the_knowledge_store(tmp_path: Path, monkeypatch) -> None:
    """`lh memory` and the hooks must answer this question the same way.

    The hooks write `MEMORY.md` and the proposal file into the store. A CLI
    still resolving the legacy path reads an empty directory and reports the
    project has no pending proposals — no error, just a wrong answer.
    """
    from lazy_harness.cli.memory_cmd import _project_memory_dir

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "nohome"))

    store = tmp_path / "store"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion   = 1\nsessions  = "sessions"\n'
        'learnings = "learnings"\nmemory    = "memory"\n'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'[harness]\nversion = "1"\n\n[knowledge]\nroot = "{store}"\n')
    monkeypatch.setattr("lazy_harness.cli.memory_cmd.config_file", lambda: config_path)

    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_text('[remote "origin"]\n\turl = git@github.com:o/x.git\n')
    monkeypatch.chdir(repo)

    assert _project_memory_dir() == store / "memory" / "github.com" / "o" / "x"


# --- batch drain: one call, many verdicts, applied back-to-front ---


def _verdict_file(tmp_path: Path, verdicts: list[dict]) -> Path:
    import json as _json

    path = tmp_path / "verdicts.json"
    path.write_text(_json.dumps(verdicts))
    return path


def test_proposals_list_json_emits_indices_the_apply_command_takes(tmp_path: Path) -> None:
    import json as _json

    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)

    result = CliRunner().invoke(
        memory, ["proposals", "list", "--json", "--memory-dir", str(memory_dir)]
    )

    assert result.exit_code == 0, result.output
    rows = _json.loads(result.output)
    assert [r["index"] for r in rows] == [1, 2, 3]
    assert rows[0]["rule"] == "Run a docs coherence pass before each release"
    assert rows[0]["rationale"] == "Docs drifted twice before releases"
    assert rows[0]["timestamp"] == "2026-05-20T10:00:00-03:00"
    assert rows[1]["rationale"] == ""


def test_proposals_apply_resolves_indices_against_the_original_listing(
    tmp_path: Path,
) -> None:
    """Verdicts are numbered against one listing, so ascending order must work.

    `accept N`/`reject N` index into a file that shrinks under them: draining
    1, 2, 3 in that order rejects proposal 1, then what used to be 3, then
    nothing. Callers were expected to know to iterate backwards. This applies
    them back-to-front internally so the caller never has to.
    """
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    verdicts = _verdict_file(
        tmp_path,
        [
            {"index": 1, "verdict": "reject", "reason": "already enforced by CI"},
            {"index": 2, "verdict": "accept"},
            {"index": 3, "verdict": "reject", "reason": "duplicate of MEMORY.md"},
        ],
    )

    result = CliRunner().invoke(
        memory,
        ["proposals", "apply", "--verdicts", str(verdicts), "--memory-dir", str(memory_dir)],
    )

    assert result.exit_code == 0, result.output
    assert parse_proposals((memory_dir / "claude-md.proposal.md").read_text()) == []

    rejected = (memory_dir / "claude-md.rejected.md").read_text()
    assert "Run a docs coherence pass before each release" in rejected
    assert "already enforced by CI" in rejected
    assert "Verify persistence with explicit file output" in rejected
    assert "duplicate of MEMORY.md" in rejected

    accepted = (memory_dir / "claude-md.accepted.md").read_text()
    assert "Never amend published commits" in accepted
    assert "Run a docs coherence pass" not in accepted


def test_proposals_apply_rejects_an_out_of_range_index_without_writing(
    tmp_path: Path,
) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    before = (memory_dir / "claude-md.proposal.md").read_text()
    verdicts = _verdict_file(
        tmp_path,
        [
            {"index": 1, "verdict": "reject", "reason": "fine"},
            {"index": 99, "verdict": "accept"},
        ],
    )

    result = CliRunner().invoke(
        memory,
        ["proposals", "apply", "--verdicts", str(verdicts), "--memory-dir", str(memory_dir)],
    )

    assert result.exit_code != 0
    assert "99" in result.output
    assert (memory_dir / "claude-md.proposal.md").read_text() == before
    assert not (memory_dir / "claude-md.rejected.md").exists()


def test_proposals_apply_rejects_a_duplicate_index_without_writing(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    before = (memory_dir / "claude-md.proposal.md").read_text()
    verdicts = _verdict_file(
        tmp_path,
        [
            {"index": 2, "verdict": "accept"},
            {"index": 2, "verdict": "reject", "reason": "changed my mind"},
        ],
    )

    result = CliRunner().invoke(
        memory,
        ["proposals", "apply", "--verdicts", str(verdicts), "--memory-dir", str(memory_dir)],
    )

    assert result.exit_code != 0
    assert "duplicate" in result.output.lower()
    assert (memory_dir / "claude-md.proposal.md").read_text() == before


def test_proposals_apply_requires_a_reason_for_every_rejection(tmp_path: Path) -> None:
    """The reason is the immunity registry's whole payload — a rejection
    without one teaches the grader nothing."""
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    before = (memory_dir / "claude-md.proposal.md").read_text()
    verdicts = _verdict_file(tmp_path, [{"index": 1, "verdict": "reject"}])

    result = CliRunner().invoke(
        memory,
        ["proposals", "apply", "--verdicts", str(verdicts), "--memory-dir", str(memory_dir)],
    )

    assert result.exit_code != 0
    assert "reason" in result.output
    assert (memory_dir / "claude-md.proposal.md").read_text() == before


def test_proposals_apply_rejects_an_unknown_verdict_value(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    verdicts = _verdict_file(tmp_path, [{"index": 1, "verdict": "maybe", "reason": "x"}])

    result = CliRunner().invoke(
        memory,
        ["proposals", "apply", "--verdicts", str(verdicts), "--memory-dir", str(memory_dir)],
    )

    assert result.exit_code != 0
    assert "maybe" in result.output


def test_proposals_apply_rejects_a_document_that_is_not_a_list(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    verdicts = tmp_path / "verdicts.json"
    verdicts.write_text('{"index": 1, "verdict": "accept"}')

    result = CliRunner().invoke(
        memory,
        ["proposals", "apply", "--verdicts", str(verdicts), "--memory-dir", str(memory_dir)],
    )

    assert result.exit_code != 0
    assert "list" in result.output.lower()


def test_proposals_apply_reports_what_it_did(tmp_path: Path) -> None:
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    verdicts = _verdict_file(
        tmp_path,
        [
            {"index": 1, "verdict": "reject", "reason": "already enforced by CI"},
            {"index": 2, "verdict": "accept"},
        ],
    )

    result = CliRunner().invoke(
        memory,
        ["proposals", "apply", "--verdicts", str(verdicts), "--memory-dir", str(memory_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "1 accepted" in result.output
    assert "1 rejected" in result.output
    assert "1 pending" in result.output


def test_proposals_apply_leaves_the_untouched_proposals_intact(tmp_path: Path) -> None:
    """Line spans are computed against the original text.

    Removing a proposal shifts every line after it, so a partial drain applied
    in the wrong order corrupts the entries it was supposed to leave alone.
    """
    from lazy_harness.cli.memory_cmd import memory

    memory_dir = tmp_path / "memory"
    _write_proposals(memory_dir)
    verdicts = _verdict_file(
        tmp_path,
        [
            {"index": 1, "verdict": "reject", "reason": "already enforced by CI"},
            {"index": 2, "verdict": "accept"},
        ],
    )

    result = CliRunner().invoke(
        memory,
        ["proposals", "apply", "--verdicts", str(verdicts), "--memory-dir", str(memory_dir)],
    )

    assert result.exit_code == 0, result.output
    remaining = parse_proposals((memory_dir / "claude-md.proposal.md").read_text())
    assert [p.rule for p in remaining] == ["Verify persistence with explicit file output"]
    assert remaining[0].rationale == "A write was claimed that never happened"
    assert remaining[0].timestamp == "2026-05-27T09:30:00-03:00"
