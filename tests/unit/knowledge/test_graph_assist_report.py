"""`lh knowledge graph-assist report`: the §6 metrics of the graph-assist design.

The core (`classify`, `compute`) is pure and tested on synthetic sessions with
known counts; `collect` is tested against transcript files in the shape Claude
Code writes them, and the CLI through a parameter-less smoke test.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.agents.base import Operation, ToolCall
from lazy_harness.knowledge import graph_assist_report as rep

REPO = Path("/repo")
T0 = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _bash(command: str) -> ToolCall:
    return ToolCall(native_name="Bash", operation=Operation.RUN_COMMAND, command=command)


def _grep(pattern: str, path: str | None = None) -> ToolCall:
    return ToolCall(
        native_name="Grep",
        operation=Operation.SEARCH_CODE,
        search_pattern=pattern,
        search_path=Path(path) if path else None,
    )


def _codex_exec(program: str) -> ToolCall:
    return ToolCall(native_name="exec", operation=None, raw_input={"input": program})


# --- classify ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "kinds"),
    [
        (_bash("graphify query 'who calls x'"), ["graphify"]),
        (_bash("cd /repo && graphify explain Config"), ["graphify"]),
        (_bash("graphify update ."), []),
        (ToolCall(native_name="mcp__graphify__query_graph", operation=None), ["graphify"]),
        (_bash("grep -rn check_version src"), ["code_grep"]),
        (_bash("rg 'a.*b' src"), ["code_grep"]),
        (_bash("grep foo /var/log/x"), []),
        (_bash("cat x | grep foo"), []),
        (_grep("anything"), ["code_grep"]),
        (_grep("x", "/elsewhere"), []),
        (_bash("ls"), []),
        (
            _codex_exec(
                'const r = await tools.exec_command({"cmd":"rg -n check_version src"});\n'
                'const g = await tools.exec_command({"cmd":"graphify path \\"A\\" \\"B\\""});'
            ),
            ["code_grep", "graphify"],
        ),
        (_codex_exec("await tools.mcp__graphify__get_neighbors({})"), ["graphify"]),
        (_codex_exec("await tools.exec_command({cmd: `ls`})"), []),
    ],
)
def test_classify(tool: ToolCall, kinds: list[str]) -> None:
    assert [c.kind for c in rep.classify(tool, REPO, REPO, T0)] == kinds


def test_classify_keeps_the_identifier_for_deflection() -> None:
    [call] = rep.classify(_bash("grep -rn check_version src"), REPO, REPO, T0)

    assert call.symbol == "check_version"


# --- compute ----------------------------------------------------------------


def _session(sid: str, agent: str, *calls: rep.Call) -> rep.SessionRecord:
    return rep.SessionRecord(agent=agent, session_id=sid, repo=REPO, calls=list(calls))


def _call(kind: str, minutes: int = 0, symbol: str | None = None) -> rep.Call:
    return rep.Call(kind=kind, ts=T0 + timedelta(minutes=minutes), symbol=symbol)


def _hit(sid: str, minutes: int, pattern: str, complete: bool = True, ms: int = 10) -> dict:
    return {
        "ts": (T0 + timedelta(minutes=minutes)).isoformat(),
        "session_id": sid,
        "pattern": pattern,
        "outcome": "hit",
        "reason": "hit",
        "latency_ms": ms,
        "complete": complete,
    }


def test_compute_counts_each_metric_per_agent() -> None:
    sessions = [
        _session("c1", "claude-code", _call("graphify"), _call("code_grep")),
        _session("c2", "claude-code", _call("code_grep", 0, "foo")),
        _session("c3", "claude-code", _call("code_grep"), _call("code_grep")),
        _session("c4", "claude-code"),
        _session("x1", "codex", _call("graphify"), _call("code_grep")),
    ]
    metrics = [
        _hit("c2", 0, "foo", ms=10),
        _hit("c2", 1, "bar", complete=False, ms=20),
        {"session_id": "c3", "outcome": "skip", "reason": "stale", "latency_ms": 3000},
    ]

    report = rep.compute(sessions, metrics)
    claude, codex = report["claude-code"], report["codex"]

    assert (claude.sessions, claude.graph_touch, claude.agent_calls) == (4, 2, 1)
    assert (claude.graphify_calls, claude.code_greps) == (1, 4)
    assert (claude.hits, claude.precise_hits) == (2, 1)
    assert claude.p95_latency_ms == 3000
    assert (codex.sessions, codex.graph_touch, codex.agent_calls) == (1, 1, 1)


def test_deflection_counts_hits_not_followed_by_a_re_search() -> None:
    sessions = [
        _session(
            "c1",
            "claude-code",
            _call("code_grep", 0, "foo"),
            _call("other", 1),
            _call("code_grep", 2, "bar"),
            _call("code_grep", 3, "bar"),
        )
    ]
    metrics = [_hit("c1", 0, "foo"), _hit("c1", 2, "bar")]

    claude = rep.compute(sessions, metrics)["claude-code"]

    assert (claude.deflection_base, claude.deflected) == (2, 1)


def test_kill_verdicts_follow_the_declared_thresholds() -> None:
    low = rep.AgentReport(agent="claude-code", sessions=10, graph_touch=1)
    low.hits, low.precise_hits, low.latencies = 4, 1, [2000]
    ok = rep.AgentReport(agent="claude-code", sessions=10, graph_touch=3)
    ok.hits, ok.precise_hits, ok.latencies = 4, 3, [10]

    assert rep.kill_reasons(low) == [
        "graph touch 10.0% < 20%",
        "hit precision 25.0% < 50%",
        "p95 latency 2000 ms > 1500 ms",
    ]
    assert rep.kill_reasons(ok) == []


def test_no_hits_is_not_a_precision_kill() -> None:
    idle = rep.AgentReport(agent="claude-code", sessions=10, graph_touch=5)

    assert rep.kill_reasons(idle) == []


# --- collect + CLI -----------------------------------------------------------


def _claude_line(ts: datetime, cwd: Path, tool: str, tool_input: dict) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "cwd": str(cwd),
            "sessionId": "sess-a",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": tool, "input": tool_input}],
            },
        }
    )


def test_collect_reads_claude_transcripts_in_indexed_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.core.config import Config, ProfileEntry

    repo = _indexed_repo(tmp_path)
    elsewhere = tmp_path / "plain"
    elsewhere.mkdir()
    config_dir = tmp_path / ".claude-cl"
    project = config_dir / "projects" / "-repo"
    project.mkdir(parents=True)
    now = datetime.now(UTC)
    (project / "sess-a.jsonl").write_text(
        _claude_line(now, repo / "src", "Grep", {"pattern": "check_version"})
        + "\n"
        + _claude_line(now, repo, "Bash", {"command": "graphify explain X"})
        + "\n"
    )
    (project / "sess-b.jsonl").write_text(
        _claude_line(now, elsewhere, "Grep", {"pattern": "x"}) + "\n"
    )
    cfg = Config()
    cfg.profiles.default = "cl"
    cfg.profiles.items = {"cl": ProfileEntry(config_dir=str(config_dir), agent="claude-code")}

    sessions, _ = rep.collect(cfg, since=now - timedelta(days=1))

    assert [(s.session_id, s.repo) for s in sessions] == [("sess-a", repo.resolve())]
    assert [c.kind for c in sessions[0].calls] == ["code_grep", "graphify"]


def test_report_command_runs_with_no_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    (tmp_path / "config.toml").write_text('[harness]\nversion = "1"\n')
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    result = CliRunner().invoke(knowledge, ["graph-assist", "report"])

    assert result.exit_code == 0, result.output
    assert "claude-code" in result.output


def _claude_profile(tmp_path: Path, name: str, repo: Path, sessions: dict[str, list[str]]) -> Path:
    config_dir = tmp_path / f".claude-{name}"
    project = config_dir / "projects" / "-repo"
    project.mkdir(parents=True)
    for sid, lines in sessions.items():
        (project / f"{sid}.jsonl").write_text("".join(line + "\n" for line in lines))
    return config_dir


def _indexed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "graphify-out").mkdir(parents=True)
    (repo / "graphify-out" / "graph.json").write_text("{}")
    return repo


def _user_line(cwd: Path, text: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "cwd": str(cwd),
            "message": {"role": "user", "content": text},
        }
    )


def test_collect_reads_each_profile_from_its_own_dir_whatever_the_env_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hook resolves its dir through CLAUDE_CONFIG_DIR; a report over every
    profile must not, or each profile reads the running session's transcripts."""
    from lazy_harness.core.config import Config, ProfileEntry

    repo = _indexed_repo(tmp_path)
    now = datetime.now(UTC)
    grep = _claude_line(now, repo, "Grep", {"pattern": "x"})
    a = _claude_profile(tmp_path, "a", repo, {"sess-a": [grep]})
    b = _claude_profile(tmp_path, "b", repo, {"sess-b": [grep]})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(a))
    cfg = Config()
    cfg.profiles.default = "a"
    cfg.profiles.items = {
        "a": ProfileEntry(config_dir=str(a), agent="claude-code"),
        "b": ProfileEntry(config_dir=str(b), agent="claude-code"),
    }

    sessions, _ = rep.collect(cfg, since=now - timedelta(days=1))

    assert sorted(s.session_id for s in sessions) == ["sess-a", "sess-b"]


def test_collect_counts_a_shared_transcript_dir_once(tmp_path: Path) -> None:
    from lazy_harness.core.config import Config, ProfileEntry

    repo = _indexed_repo(tmp_path)
    now = datetime.now(UTC)
    a = _claude_profile(
        tmp_path, "a", repo, {"sess-a": [_claude_line(now, repo, "Grep", {"pattern": "x"})]}
    )
    cfg = Config()
    cfg.profiles.default = "a"
    cfg.profiles.items = {
        "a": ProfileEntry(config_dir=str(a), agent="claude-code"),
        "a2": ProfileEntry(config_dir=str(a), agent="claude-code"),
    }

    sessions, _ = rep.collect(cfg, since=now - timedelta(days=1))

    assert [s.session_id for s in sessions] == ["sess-a"]


def test_collect_skips_sessions_that_made_no_tool_call(tmp_path: Path) -> None:
    """A headless evaluation that only answers a prompt cannot search anything;
    counting it dilutes adoption with sessions that never had the choice."""
    from lazy_harness.core.config import Config, ProfileEntry

    repo = _indexed_repo(tmp_path)
    now = datetime.now(UTC)
    a = _claude_profile(
        tmp_path,
        "a",
        repo,
        {
            "talk": [_user_line(repo, "You are evaluating a Claude Code session")],
            "work": [_claude_line(now, repo, "Read", {"file_path": str(repo / "x")})],
        },
    )
    cfg = Config()
    cfg.profiles.default = "a"
    cfg.profiles.items = {"a": ProfileEntry(config_dir=str(a), agent="claude-code")}

    sessions, _ = rep.collect(cfg, since=now - timedelta(days=1))

    assert [s.session_id for s in sessions] == ["work"]


def test_a_worktree_outside_the_main_tree_counts_toward_the_main_checkout(
    tmp_path: Path,
) -> None:
    """The hook answers from the main checkout's graph, so the report's
    population has to resolve the same way — through git, not a parent walk."""
    import subprocess

    repo = _indexed_repo(tmp_path)
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/opt/homebrew/bin"}  # fmt: skip
    for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "i"]):
        subprocess.run(["git", *args], cwd=repo, check=True, env=env, capture_output=True)
    worktree = tmp_path / "elsewhere" / "wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(worktree), "-b", "wt"],
        cwd=repo,
        check=True,
        env=env,
        capture_output=True,
    )

    assert rep._graph_repo(worktree) == repo.resolve()
    assert rep._graph_repo(tmp_path / "elsewhere") is None
