"""`lh memory reconcile` — schema drift + contradiction reporting (ADR-040).

Read-only end to end: neither detection ever writes. Detection 1 (schema
drift) is deterministic and runs by default; detection 2 (contradictions) is
an LLM call gated behind `--check-contradictions` so a bare `lh memory
reconcile` against a 22-repository store never fires 22 inference calls
nobody asked for.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli import memory_cmd as mod
from lazy_harness.cli.memory_cmd import memory
from lazy_harness.llm.invoke import InferenceError, InferenceResult


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _setup_store(tmp_path: Path, monkeypatch) -> Path:
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
    return store


def _stub_run_inference(monkeypatch, fn) -> None:
    def fake_run_inference(prompt, *, role, cfg, timeout, schema=None, model=None):
        from lazy_harness.llm.roles import resolve_role

        target = resolve_role(cfg, role)
        resolved_model = model or target.model
        output = fn(prompt)
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


def test_reconcile_reports_no_drift_on_a_uniform_log(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    _write_jsonl(
        memory_dir / "decisions.jsonl",
        [{"ts": "t1", "type": "decision", "summary": "a"}],
    )

    result = CliRunner().invoke(memory, ["reconcile", "--memory-dir", str(memory_dir)])

    assert result.exit_code == 0, result.output
    assert "No schema drift found" in result.output


def test_reconcile_reports_schema_drift_with_memory_dir(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    _write_jsonl(
        memory_dir / "decisions.jsonl",
        [
            {"date": "d", "decision": "old", "rationale": "r", "alternatives": []},
            *(
                [
                    {
                        "ts": "t",
                        "type": "decision",
                        "summary": "s",
                        "context": "c",
                        "alternatives": [],
                        "rationale": "r",
                        "project": "p",
                        "tags": [],
                    }
                ]
                * 5
            ),
        ],
    )

    result = CliRunner().invoke(memory, ["reconcile", "--memory-dir", str(memory_dir)])

    assert result.exit_code == 0, result.output
    assert "1 line" in result.output  # the one drifted line
    assert "decision" in result.output  # the drifted field name surfaces


def test_reconcile_never_writes_the_jsonl(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    path = memory_dir / "decisions.jsonl"
    _write_jsonl(path, [{"date": "d", "decision": "old"}, {"ts": "t", "summary": "new"}])
    before = path.read_text()

    CliRunner().invoke(memory, ["reconcile", "--memory-dir", str(memory_dir)])

    assert path.read_text() == before


def test_reconcile_skips_contradiction_pass_by_default(tmp_path: Path, monkeypatch) -> None:
    memory_dir = tmp_path / "memory"
    _write_jsonl(memory_dir / "decisions.jsonl", [{"ts": "t", "summary": "a"}])

    called = []
    _stub_run_inference(monkeypatch, lambda p: called.append(p) or "irrelevant")

    result = CliRunner().invoke(memory, ["reconcile", "--memory-dir", str(memory_dir)])

    assert result.exit_code == 0, result.output
    assert called == []


def test_reconcile_check_contradictions_invokes_the_llm(tmp_path: Path, monkeypatch) -> None:
    memory_dir = tmp_path / "memory"
    _write_jsonl(
        memory_dir / "decisions.jsonl",
        [
            {"ts": "t1", "summary": "use postgres"},
            {"ts": "t2", "summary": "use sqlite instead of postgres"},
        ],
    )

    captured = {}

    def fake_invoke(prompt):
        captured["prompt"] = prompt
        return "use postgres (t1) contradicts use sqlite instead of postgres (t2)"

    _stub_run_inference(monkeypatch, fake_invoke)

    result = CliRunner().invoke(
        memory, ["reconcile", "--memory-dir", str(memory_dir), "--check-contradictions"]
    )

    assert result.exit_code == 0, result.output
    assert "use postgres" in captured["prompt"]
    assert "contradicts" in result.output


def test_reconcile_check_contradictions_reports_none_found_quietly(
    tmp_path: Path, monkeypatch
) -> None:
    memory_dir = tmp_path / "memory"
    _write_jsonl(memory_dir / "decisions.jsonl", [{"ts": "t1", "summary": "a"}])

    _stub_run_inference(monkeypatch, lambda p: "No contradictions found.")

    result = CliRunner().invoke(
        memory, ["reconcile", "--memory-dir", str(memory_dir), "--check-contradictions"]
    )

    assert result.exit_code == 0, result.output
    # No per-project block is printed when the LLM found nothing — a clean
    # store should not scroll past the "Checking..." line.
    assert str(memory_dir) not in result.output


def test_reconcile_never_resolves_a_contradiction_itself() -> None:
    """The command reports; it does not pick a winner. There is no --apply option."""
    param_names = {p.name for p in memory.commands["reconcile"].params}

    assert "do_apply" not in param_names
    assert "apply" not in param_names


def test_reconcile_default_scope_is_the_whole_knowledge_store(tmp_path: Path, monkeypatch) -> None:
    """Parameter-less smoke test pairing the `--memory-dir` tests above:
    default resolution must scan every project the store knows about, not
    `Path.cwd()`."""
    store = _setup_store(tmp_path, monkeypatch)
    project_dir = store / "memory" / "github.com" / "o" / "repo"
    _write_jsonl(
        project_dir / "decisions.jsonl",
        [
            {"date": "d", "decision": "old"},
            *([{"ts": "t", "summary": "s"}] * 3),
        ],
    )

    result = CliRunner().invoke(memory, ["reconcile"])

    assert result.exit_code == 0, result.output
    assert "decision" in result.output


def test_reconcile_no_projects_in_an_empty_store(tmp_path: Path, monkeypatch) -> None:
    _setup_store(tmp_path, monkeypatch)

    result = CliRunner().invoke(memory, ["reconcile"])

    assert result.exit_code == 0, result.output
    assert "no project memory" in result.output.lower()
