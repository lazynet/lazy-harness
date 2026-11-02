"""One headless-isolation argv for `claude -p`, two builders (backlog: one argv).

The literals below were captured from `main` @ ba00bec BEFORE the refactor, so
they prove the shared definition changed no byte; they are not derived from it.
"""

from __future__ import annotations

import subprocess

import pytest

from lazy_harness.agents.claude_code import NO_TOOLS, ClaudeCodeAdapter

_ISOLATION = ["--output-format", "json", "--setting-sources", ""]


@pytest.mark.parametrize(
    ("model", "allowed_tools", "expected"),
    [
        (None, None, ["-p", *_ISOLATION]),
        ("haiku", None, ["-p", *_ISOLATION, "--model", "haiku"]),
        (None, ["Read", "Write"], ["-p", *_ISOLATION, "--allowedTools", "Read,Write"]),
        (
            "sonnet",
            [],
            ["-p", *_ISOLATION, "--model", "sonnet", "--disallowedTools", ",".join(NO_TOOLS)],
        ),
    ],
)
def test_exec_argv_is_byte_identical_to_the_pre_refactor_capture(
    model: str | None, allowed_tools: list[str] | None, expected: list[str]
) -> None:
    argv = ClaudeCodeAdapter().headless_argv(model=model, allowed_tools=allowed_tools)

    assert argv == expected


def test_exec_argv_no_tools_list_is_the_pre_refactor_capture() -> None:
    assert ",".join(NO_TOOLS) == (
        "Task,Bash,Glob,Grep,Read,Edit,Write,NotebookEdit,WebFetch,WebSearch,TodoWrite"
    )


def test_evaluator_argv_is_byte_identical_to_the_pre_refactor_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.llm import claude as claude_mod

    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003 — mirrors subprocess.run
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(claude_mod.subprocess, "run", fake_run)

    claude_mod.ClaudeBackend().complete("hi", "m", 5)

    assert seen == [["claude", "-p", "--model", "m", *_ISOLATION, "--no-session-persistence"]]


def test_both_builders_carry_the_shared_isolation_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dropping a shared flag from either builder must fail here."""
    from lazy_harness.core.claude_headless import HEADLESS_ISOLATION_FLAGS, HEADLESS_PRINT_FLAG
    from lazy_harness.llm import claude as claude_mod

    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(claude_mod.subprocess, "run", fake_run)
    claude_mod.ClaudeBackend().complete("hi", "m", 5)
    evaluator = seen[0]
    exec_argv = ClaudeCodeAdapter().headless_argv(model="m", allowed_tools=None)

    for argv in (evaluator, exec_argv):
        assert HEADLESS_PRINT_FLAG in argv
        start = argv.index(HEADLESS_ISOLATION_FLAGS[0])
        assert argv[start : start + len(HEADLESS_ISOLATION_FLAGS)] == list(HEADLESS_ISOLATION_FLAGS)
