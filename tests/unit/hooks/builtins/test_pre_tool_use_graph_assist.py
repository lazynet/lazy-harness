"""`pre-tool-use-graph-assist`: answer a code-symbol search from the graph.

Spec: `specs/designs/2026-09-24-graph-assist-design.md` §3.1, §3.5, §4.
Repositories are real `git init` checkouts so the freshness rule (graph mtime
≥ HEAD commit time) runs against git itself; both ends are frozen — the commit
date through `GIT_COMMITTER_DATE`, the graph mtime through `os.utime`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from lazy_harness.agents.base import HookEvent, Operation, ToolCall
from lazy_harness.hooks.builtins import pre_tool_use_graph_assist as hook

COMMIT_TS = 1_750_000_000

GRAPH = {
    "nodes": [
        {
            "id": "a",
            "label": "check_version()",
            "source_file": "src/pkg/graphify.py",
            "source_location": "L64",
            "file_type": "code",
        },
        {
            "id": "b",
            "label": "check_version()",
            "source_file": "src/pkg/engram.py",
            "source_location": "L59",
            "file_type": "code",
        },
    ],
    "links": [],
}


def _git(root: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": f"@{COMMIT_TS} +0000",
        "GIT_COMMITTER_DATE": f"@{COMMIT_TS} +0000",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env)


def _repo(tmp_path: Path, *, graph: dict | None = GRAPH, graph_offset: int = 60) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    _git(root, "init", "-q")
    (root / "README").write_text("x")
    _git(root, "add", "README")
    _git(root, "commit", "-qm", "init")
    if graph is not None:
        out = root / "graphify-out"
        out.mkdir()
        (out / "graph.json").write_text(json.dumps(graph))
        ts = COMMIT_TS + graph_offset
        os.utime(out / "graph.json", (ts, ts))
    return root


@pytest.fixture
def metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "logs" / "graph_assist_metrics.jsonl"
    monkeypatch.setattr(hook, "_metrics_file", lambda profile: path)
    return path


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _event(cwd: Path, native_name: str, raw_input: dict) -> HookEvent:
    """The normalised call the adapter would hand over, without `raw_input`."""
    operation = {
        "Bash": Operation.RUN_COMMAND,
        "Grep": Operation.SEARCH_CODE,
        "Read": Operation.READ_FILE,
    }[native_name]
    path = raw_input.get("path")
    return HookEvent(
        event="pre_tool_use",
        profile="p",
        session_id="sess-1",
        cwd=cwd,
        transcript_path=None,
        tool=ToolCall(
            native_name=native_name,
            operation=operation,
            command=raw_input.get("command"),
            search_pattern=raw_input.get("pattern"),
            search_path=Path(path) if path else None,
        ),
    )


def test_a_symbol_grep_gets_the_definitions(tmp_path: Path, metrics: Path) -> None:
    root = _repo(tmp_path)

    decision = hook.main(_event(root, "Bash", {"command": "grep -rn check_version src"}))

    assert "src/pkg/graphify.py:64" in decision.additional_context
    assert "src/pkg/engram.py:59" in decision.additional_context
    assert decision.verdict is None
    [line] = _lines(metrics)
    assert line["outcome"] == "hit"
    assert line["definitions"] == 2
    assert line["symbol_in_output"] is True
    assert line["pattern"] == "check_version"
    assert line["session_id"] == "sess-1"
    assert line["repo"] == str(root)
    assert isinstance(line["latency_ms"], int)


def test_the_grep_tool_with_no_path_gets_the_definitions(tmp_path: Path, metrics: Path) -> None:
    root = _repo(tmp_path)

    decision = hook.main(_event(root, "Grep", {"pattern": "check_version"}))

    assert "2 definitions" in decision.additional_context


def test_a_search_from_a_subdirectory_resolves_the_repo_root(tmp_path: Path, metrics: Path) -> None:
    root = _repo(tmp_path)

    decision = hook.main(_event(root / "src", "Grep", {"pattern": "check_version"}))

    assert "2 definitions" in decision.additional_context


@pytest.mark.parametrize(
    ("native", "raw", "reason"),
    [
        ("Bash", {"command": "cat x | grep check_version"}, "not_search"),
        ("Bash", {"command": "grep check_version /var/log/x"}, "not_search"),
        ("Bash", {"command": "grep 'a.*b' src"}, "not_search"),
        ("Bash", {"command": 'grep "two words" src'}, "not_search"),
        ("Grep", {"pattern": "check_version", "path": "/elsewhere"}, "not_search"),
        ("Grep", {"pattern": "absent_symbol"}, "miss"),
    ],
)
def test_silent_cases_log_their_reason(
    tmp_path: Path, metrics: Path, native: str, raw: dict, reason: str
) -> None:
    root = _repo(tmp_path)

    decision = hook.main(_event(root, native, raw))

    assert decision.additional_context == ""
    assert _lines(metrics)[-1]["outcome"] in ("skip", "miss")
    assert _lines(metrics)[-1]["reason"] == reason


def test_a_stale_graph_stays_silent(tmp_path: Path, metrics: Path) -> None:
    root = _repo(tmp_path, graph_offset=-60)

    decision = hook.main(_event(root, "Grep", {"pattern": "check_version"}))

    assert decision.additional_context == ""
    assert _lines(metrics)[-1]["reason"] == "stale"


def test_a_graph_exactly_at_head_time_is_fresh(tmp_path: Path, metrics: Path) -> None:
    root = _repo(tmp_path, graph_offset=0)

    decision = hook.main(_event(root, "Grep", {"pattern": "check_version"}))

    assert "2 definitions" in decision.additional_context


def test_a_repo_without_a_graph_stays_silent(tmp_path: Path, metrics: Path) -> None:
    root = _repo(tmp_path, graph=None)

    decision = hook.main(_event(root, "Grep", {"pattern": "check_version"}))

    assert decision.additional_context == ""
    assert _lines(metrics)[-1]["reason"] == "no_graph"


def test_a_worktree_without_its_own_graph_stays_silent(tmp_path: Path, metrics: Path) -> None:
    root = _repo(tmp_path)
    worktree = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", str(worktree), "-b", "wt")

    decision = hook.main(_event(worktree, "Grep", {"pattern": "check_version"}))

    assert decision.additional_context == ""
    assert _lines(metrics)[-1]["reason"] == "no_graph"


def test_outside_any_repo_stays_silent(tmp_path: Path, metrics: Path) -> None:
    decision = hook.main(_event(tmp_path, "Grep", {"pattern": "check_version"}))

    assert decision.additional_context == ""
    assert _lines(metrics)[-1]["reason"] == "no_repo"


def test_an_index_build_past_the_deadline_stays_silent(
    tmp_path: Path, metrics: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    monkeypatch.setattr(hook.graph_assist, "load_index", lambda repo_root: None)

    decision = hook.main(_event(root, "Grep", {"pattern": "check_version"}))

    assert decision.additional_context == ""
    assert _lines(metrics)[-1]["reason"] == "index_building"


def test_an_unexpected_error_is_swallowed_and_logged(
    tmp_path: Path, metrics: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)

    def boom(repo_root: Path) -> None:
        raise KeyError("x")

    monkeypatch.setattr(hook.graph_assist, "load_index", boom)

    decision = hook.main(_event(root, "Grep", {"pattern": "check_version"}))

    assert decision.additional_context == ""
    assert _lines(metrics)[-1]["reason"] == "error:KeyError"


def test_a_metrics_write_failure_still_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory must go")
    monkeypatch.setattr(hook, "_metrics_file", lambda profile: blocker / "m.jsonl")

    decision = hook.main(_event(root, "Grep", {"pattern": "check_version"}))

    assert "2 definitions" in decision.additional_context


def test_a_non_search_tool_is_not_logged(tmp_path: Path, metrics: Path) -> None:
    """Only Bash|Grep evaluations count; anything else never reached the filter."""
    root = _repo(tmp_path)

    decision = hook.main(_event(root, "Read", {"file_path": str(root / "README")}))

    assert decision.additional_context == ""
    assert not metrics.exists()


def test_the_output_is_information_not_an_order(tmp_path: Path, metrics: Path) -> None:
    root = _repo(tmp_path)

    decision = hook.main(_event(root, "Grep", {"pattern": "check_version"}))

    assert "MANDATORY" not in decision.additional_context
    assert "MUST" not in decision.additional_context


def test_inspected_tools_match_the_registered_matcher() -> None:
    from lazy_harness.hooks.loader import resolve_builtin_spec

    spec = resolve_builtin_spec("pre-tool-use-graph-assist")

    assert spec is not None
    assert set((spec.matcher_for("pre_tool_use") or "").split("|")) == hook.INSPECTED_TOOLS
    assert spec.agents == frozenset({"claude-code"})
    assert spec.blocking is False


@pytest.mark.parametrize("stdin", ["{not json", "null", "42", "[1, 2]", '"text"'])
def test_malformed_or_wrong_type_payloads_exit_zero_silently(stdin: str) -> None:
    from lazy_harness.hooks.runner import run_hook

    output = run_hook("pre-tool-use-graph-assist", profile="p", stdin_text=stdin)

    assert output.exit_code == 0
    assert output.stdout is None


def test_a_shell_command_running_no_search_tool_is_not_logged(
    tmp_path: Path, metrics: Path
) -> None:
    root = _repo(tmp_path)

    decision = hook.main(_event(root, "Bash", {"command": "ls src && git status"}))

    assert decision.additional_context == ""
    assert not metrics.exists()
