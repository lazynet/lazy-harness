"""`lh memory status` — what memory exists for this project, and where.

The command the governance contract already names: `CLAUDE.md` requires that
every documented memory path match this command's output. Its job is the
inventory, not the verdict — `lh doctor` owns the hygiene judgement.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.memory_cmd import memory


def _setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
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
        f'root = "{store}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    return store, profile


def _repo(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text(
        f'[remote "origin"]\n\turl = git@github.com:o/{name}.git\n'
    )
    return root


def test_status_reports_the_store_path_it_resolves_for_the_cwd(tmp_path: Path, monkeypatch) -> None:
    """No --memory-dir: this is the default-resolution path the hooks use."""
    store, _ = _setup(tmp_path, monkeypatch)
    repo = _repo(tmp_path, "widget")
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(memory, ["status"])

    assert result.exit_code == 0, result.output
    assert str(store / "memory" / "github.com" / "o" / "widget") in result.output


def test_status_reports_memory_md_size_in_lines_and_bytes(tmp_path: Path) -> None:
    """Both dimensions: the cap that bit before measured lines while the cost
    was bytes."""
    d = tmp_path / "memory"
    d.mkdir()
    (d / "MEMORY.md").write_text("- one\n- two\n- three\n")

    result = CliRunner().invoke(memory, ["status", "--memory-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert "3 lines" in result.output
    assert "20 B" in result.output


def test_status_counts_memory_documents_apart_from_the_index_and_proposals(
    tmp_path: Path,
) -> None:
    """MEMORY.md is the index and claude-md.* are the proposal ledgers. Counting
    every .md in the directory would report 5 memories where there are 2."""
    d = tmp_path / "memory"
    d.mkdir()
    (d / "MEMORY.md").write_text("- index\n")
    (d / "claude-md.proposal.md").write_text("")
    (d / "claude-md.rejected.md").write_text("")
    (d / "gh_auth_dual_accounts.md").write_text("body\n")
    (d / "worktree_show_toplevel_gotcha.md").write_text("body\n")

    result = CliRunner().invoke(memory, ["status", "--memory-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert "2 files" in result.output


def test_status_reports_jsonl_counts_and_the_last_date_under_either_ts_key(
    tmp_path: Path,
) -> None:
    """The store holds both spellings: 387 of this repo's 388 decisions carry
    `ts`, one legacy row carries `timestamp`. Reading only one undercounts."""
    d = tmp_path / "memory"
    d.mkdir()
    (d / "decisions.jsonl").write_text(
        '{"timestamp": "2026-04-01T10:00:00-03:00", "summary": "legacy row"}\n'
        '{"ts": "2026-08-31T16:01:45-03:00", "summary": "current row"}\n'
    )

    result = CliRunner().invoke(memory, ["status", "--memory-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert "2 records" in result.output
    assert "2026-08-31" in result.output


def test_status_counts_a_corrupt_jsonl_line_without_failing(tmp_path: Path) -> None:
    """These files are append-only and written by hooks. A half-written line
    must not take the whole report down, and must not vanish from the count."""
    d = tmp_path / "memory"
    d.mkdir()
    (d / "failures.jsonl").write_text(
        '{"ts": "2026-08-30T09:00:00-03:00", "summary": "good"}\n'
        '{"ts": "2026-08-31T09:00:00-03:00", "summ\n'
    )

    result = CliRunner().invoke(memory, ["status", "--memory-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert "2 records" in result.output
    assert "2026-08-30" in result.output


def test_status_counts_proposals_by_rule_not_by_timestamp_block(tmp_path: Path) -> None:
    """One timestamped block can carry several rules — this repo's rejected
    ledger holds 78 rules across 77 blocks — and `proposals list` numbers rules,
    so counting blocks would disagree with the command that drains the queue."""
    d = tmp_path / "memory"
    d.mkdir()
    (d / "claude-md.proposal.md").write_text(
        "## 2026-08-31T11:00:13-03:00\n\n"
        "- **Rule:** first pending\n"
        "  - **Rationale:** why\n"
    )
    (d / "claude-md.rejected.md").write_text(
        "## 2026-08-31T13:48:15-03:00\n"
        "rejected: 2026-09-01\n"
        "reason: duplicate\n\n"
        "- **Rule:** one\n"
        "  - **Rationale:** why\n"
        "- **Rule:** two in the same block\n"
        "  - **Rationale:** why\n"
    )

    result = CliRunner().invoke(memory, ["status", "--memory-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert "1 pending" in result.output
    assert "2 rejected" in result.output


def test_status_surfaces_a_populated_legacy_directory_beside_the_store(
    tmp_path: Path, monkeypatch
) -> None:
    """The split this exists to make visible: memory in the agent's own project
    dir is not the store, and nothing in lh reads it once a store resolves."""
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.paths import agent_runtime_dir
    from lazy_harness.hooks.builtins._shared import resolve_memory_dir

    store, profile = _setup(tmp_path, monkeypatch)
    repo = _repo(tmp_path, "widget")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(profile))
    monkeypatch.chdir(repo)

    agent = get_agent("claude-code")
    legacy = (
        resolve_memory_dir(
            None,
            agent_dir=agent_runtime_dir(agent),
            sessions_subdir=agent.session_dirs().get("sessions") or "projects",
            cwd=Path.cwd(),
        )
        / "memory"
    )
    legacy.mkdir(parents=True)
    (legacy / "MEMORY.md").write_text("- one\n- two\n")
    (legacy / "a_gotcha.md").write_text("body\n")

    result = CliRunner().invoke(memory, ["status"])

    assert result.exit_code == 0, result.output
    assert str(store / "memory" / "github.com" / "o" / "widget") in result.output
    assert str(legacy) in result.output
    assert "lh memory legacy-check" in result.output


def test_status_stays_quiet_about_a_legacy_directory_that_is_empty(
    tmp_path: Path, monkeypatch
) -> None:
    """An empty leftover directory is noise, not a finding."""
    _setup(tmp_path, monkeypatch)
    repo = _repo(tmp_path, "widget")
    profile = tmp_path / "profile-lazy"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(profile))
    monkeypatch.chdir(repo)

    result = CliRunner().invoke(memory, ["status"])

    assert result.exit_code == 0, result.output
    assert "lh memory legacy-check" not in result.output


def test_status_says_a_keyless_checkout_is_why_the_store_is_not_used(
    tmp_path: Path, monkeypatch
) -> None:
    """No remote means a `local/` key, and memory deliberately stays out of the
    store — it is a git repository that gets pushed, and two machines' unrelated
    directories would merge under one name. Without this line the report shows a
    profile path and no reason for it."""
    _setup(tmp_path, monkeypatch)
    loose = tmp_path / "loose"
    (loose / ".git").mkdir(parents=True)
    (loose / ".git" / "config").write_text("[core]\n\tbare = false\n")
    monkeypatch.chdir(loose)

    result = CliRunner().invoke(memory, ["status"])

    assert result.exit_code == 0, result.output
    assert "no git remote" in result.output
