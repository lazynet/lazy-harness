"""ClaudeBackend — subprocess call extracted verbatim from compound_loop (ADR-033)."""

from __future__ import annotations

import subprocess

import pytest


class _FakeCompleted:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def test_claude_backend_satisfies_protocol() -> None:
    from lazy_harness.llm.base import LLMBackend
    from lazy_harness.llm.claude import ClaudeBackend

    assert isinstance(ClaudeBackend(), LLMBackend)


def test_name_and_default_model() -> None:
    from lazy_harness.llm.claude import ClaudeBackend

    backend = ClaudeBackend()
    assert backend.name == "claude"
    assert backend.default_model() == "claude-haiku-4-5-20251001"


def test_complete_runs_claude_subprocess_with_existing_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Argv, prompt-on-stdin, and timeout must match the historical invoke_claude call."""
    from lazy_harness.llm import claude as claude_mod

    captured: dict = {}

    def fake_run(argv, **kwargs):  # noqa: ANN001, ANN003 — mirrors subprocess.run
        captured["argv"] = argv
        captured["input"] = kwargs.get("input")
        captured["timeout"] = kwargs.get("timeout")
        captured["capture_output"] = kwargs.get("capture_output")
        captured["text"] = kwargs.get("text")
        return _FakeCompleted("  the answer \n")

    monkeypatch.setattr(claude_mod.subprocess, "run", fake_run)

    result = claude_mod.ClaudeBackend().complete("hello", "test-model", 42)

    assert result == "the answer"
    assert captured["argv"] == ["claude", "-p", "--model", "test-model", "--output-format", "text"]
    assert captured["input"] == "hello"
    assert captured["timeout"] == 42
    assert captured["capture_output"] is True
    assert captured["text"] is True


def test_complete_empty_stdout_returns_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.llm import claude as claude_mod

    monkeypatch.setattr(claude_mod.subprocess, "run", lambda *a, **kw: _FakeCompleted("   \n"))
    assert claude_mod.ClaudeBackend().complete("p", "m", 1) == ""


@pytest.mark.parametrize(
    "exc",
    [
        subprocess.TimeoutExpired(cmd="claude", timeout=1),
        FileNotFoundError("claude not on PATH"),
        OSError("boom"),
    ],
)
def test_complete_maps_subprocess_failures_to_llm_backend_error(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    from lazy_harness.llm import claude as claude_mod
    from lazy_harness.llm.base import LLMBackendError

    def fake_run(*a, **kw):  # noqa: ANN002, ANN003
        raise exc

    monkeypatch.setattr(claude_mod.subprocess, "run", fake_run)
    with pytest.raises(LLMBackendError):
        claude_mod.ClaudeBackend().complete("p", "m", 1)
